"""Run all gates over a run directory, write reports, and apply demotions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from nmt_engine.gates.base import REGISTRY, GateConfig, GateResult
from nmt_engine.schema import Record
from nmt_engine.store import RunData, SchemaError, load_run


@dataclass
class GateReport:
    run_dir: Path
    results: list[GateResult]
    schema_errors: list[str]

    @property
    def passed(self) -> bool:
        return not self.schema_errors and all(r.passed for r in self.results)

    def failed_gates(self) -> list[int]:
        return [r.gate.number for r in self.results if not r.passed]

    def as_dict(self) -> dict:
        return {
            "run_dir": self.run_dir.name,
            "passed": self.passed,
            "schema_errors": self.schema_errors,
            "gates": [r.as_dict() for r in self.results],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Gate report: {self.run_dir.name}",
            "",
            f"**Overall: {'PASS' if self.passed else 'FAIL'}**",
            "",
        ]
        if self.schema_errors:
            lines += ["## Schema errors", ""] + [f"- {e}" for e in self.schema_errors] + [""]
        lines += ["| Gate | Title | Result | Findings |", "|---|---|---|---|"]
        for r in self.results:
            res = "pass" if r.passed else "FAIL"
            lines.append(f"| {r.gate.number} | {r.gate.title} | {res} | {len(r.findings)} |")
        for r in self.results:
            if r.findings:
                lines += ["", f"## Gate {r.gate.number}: {r.gate.title}", ""]
                lines += [
                    f"- `{f.object_type}:{f.object_id}` [{f.action}] {f.message}"
                    for f in r.findings
                ]
        return "\n".join(lines) + "\n"


def run_gates(
    run_dir: Path, cfg: GateConfig | None = None, only: list[int] | None = None
) -> GateReport:
    cfg = cfg or GateConfig()
    run_dir = Path(run_dir)
    try:
        run = load_run(run_dir)
    except SchemaError as exc:
        return GateReport(run_dir, [], exc.errors)
    return GateReport(run_dir, evaluate(run, cfg, only), [])


def evaluate(run: RunData, cfg: GateConfig, only: list[int] | None = None) -> list[GateResult]:
    results = []
    for num in sorted(REGISTRY):
        if only and num not in only:
            continue
        g = REGISTRY[num]
        findings = sorted(
            set(g.fn(run, cfg)), key=lambda f: (f.object_type, f.object_id, f.message)
        )
        results.append(GateResult(g, findings))
    return results


def write_reports(report: GateReport, out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = Path(out_dir or report.run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath, mpath = out_dir / "gate_report.json", out_dir / "gate_report.md"
    jpath.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", "utf-8")
    mpath.write_text(report.to_markdown(), "utf-8")
    return jpath, mpath


def _bump(rec: Record, flag: str, **changes) -> Record:
    data = rec.model_dump()
    data.update(changes)
    data["rev"] = rec.rev + 1
    data["flags"] = sorted(set(rec.flags) | {flag})
    return type(rec).model_validate(data)


def demote(run_dir: Path, cfg: GateConfig | None = None) -> dict:
    """Apply gate actions as new store revisions. Returns a summary.

    demote        PUBLIC_VOICE -> HYPOTHESIS (gate 1)
    single_signal claim marked single_signal; removed from Segment/why_we_win; Jobs -> thin
    recount       claim voices set to the distinct-author count
    collapse      claim voices set to the post-astroturf count
    drop          source retracted; refs to it removed; claims left without refs retracted;
                  Calcs using a retracted source or claim retracted
    flag          object gets a gNN flag (excluded from display)
    """
    cfg = cfg or GateConfig()
    run = load_run(Path(run_dir))
    results = evaluate(run, cfg)
    changed: dict[tuple[str, str], Record] = {}
    attr = {
        "claim": run.claims,
        "source": run.sources,
        "calc": run.calcs,
        "segment": run.segments,
        "strategy": run.strategies,
        "synthetic": run.synthetics,
        "sim_run": run.sim_runs,
        "job": run.jobs,
    }

    def get(t: str, i: str) -> Record | None:
        return changed.get((t, i)) or attr.get(t, {}).get(i)

    def put(t: str, rec: Record) -> None:
        changed[(t, rec.id)] = rec

    from nmt_engine.gates.g12_astroturf import effective_voices, near_duplicate_clusters

    clusters = None
    dropped_sources: set[str] = set()
    summary: dict[str, list[str]] = {}
    for res in results:
        flag = res.gate.id
        for f in res.findings:
            summary.setdefault(f.action, []).append(f"{f.object_type}:{f.object_id}")
            rec = get(f.object_type, f.object_id)
            if rec is None:
                continue
            if f.action == "demote" and f.object_type == "claim":
                put("claim", _bump(rec, flag, status="HYPOTHESIS"))
            elif f.action == "single_signal" and f.object_type == "claim":
                put("claim", _bump(rec, flag, single_signal=True))
                for seg in run.segments.values():
                    cur = get("segment", seg.id)
                    if rec.id in cur.claim_ids:
                        ids = [c for c in cur.claim_ids if c != rec.id]
                        put("segment", _bump(cur, flag, claim_ids=ids))
                for st in run.strategies.values():
                    cur = get("strategy", st.id)
                    if rec.id in cur.why_we_win.claim_ids:
                        w = cur.why_we_win.model_dump()
                        w["claim_ids"] = [c for c in w["claim_ids"] if c != rec.id]
                        put("strategy", _bump(cur, flag, why_we_win=w))
                for job in run.jobs.values():
                    cur = get("job", job.id)
                    if rec.id in cur.claim_ids:
                        put("job", _bump(cur, flag, thin=True))
            elif f.action == "recount" and f.object_type == "claim":
                from nmt_engine.gates.g02_voices import distinct_authors

                n = len(distinct_authors(run, rec))
                put("claim", _bump(rec, flag, voices=n, single_signal=n < 2 or rec.single_signal))
            elif f.action == "collapse" and f.object_type == "claim":
                if clusters is None:
                    clusters = near_duplicate_clusters(run, cfg)
                eff = effective_voices(run, rec, clusters)
                put(
                    "claim",
                    _bump(rec, flag, voices=eff, single_signal=eff < 2 or rec.single_signal),
                )
            elif f.action == "drop" and f.object_type == "source":
                dropped_sources.add(rec.id)
                put("source", _bump(rec, flag, retracted=True))
            elif f.action == "drop" and f.object_type == "claim":
                refs = [r for r in rec.source_refs if r.source_id in run.sources]
                put(
                    "claim",
                    _bump(
                        rec, flag, source_refs=[r.model_dump() for r in refs], retracted=not refs
                    ),
                )
            else:
                put(f.object_type, _bump(rec, flag))
    if dropped_sources:
        for claim in run.claims.values():
            cur = get("claim", claim.id)
            if any(r.source_id in dropped_sources for r in cur.source_refs):
                refs = [r for r in cur.source_refs if r.source_id not in dropped_sources]
                put(
                    "claim",
                    _bump(
                        cur,
                        "dropped_source",
                        source_refs=[r.model_dump() for r in refs],
                        retracted=not refs,
                        single_signal=True,
                    ),
                )
    gone_claims = {c.id for c in run.claims.values() if (get("claim", c.id) or c).retracted}
    for calc in run.calcs.values():
        cur = get("calc", calc.id)
        if any(i.source_id in dropped_sources or i.claim_id in gone_claims for i in cur.inputs):
            put("calc", _bump(cur, "dropped_source", retracted=True))
    store = run.store
    for rec in changed.values():
        store.append(rec)
    out = {k: sorted(set(v)) for k, v in summary.items()}
    (Path(run_dir) / "demote_report.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    return out
