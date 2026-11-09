"""L3 on a harvest + L4 node status (ARCHITECTURE_v3 §3 L3-L4, §5 T2, §8 A4-A5).

A qualifying voice is a distinct salted author hash whose post the producer calls USER and naming a
Solution they use or used, from a customer-voice evidence family, with a verbatim quote for the
node. Supported or contradicted needs at least MIN_VOICES voices from at least MIN_FAMILIES
families; a node meeting both is unknown and flagged contested. Context-only families and
simulation output never count."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from nmt_engine.collect.run import collector_on
from nmt_engine.llm import LLM
from nmt_engine.schema import CUSTOMER_VOICE
from nmt_engine.store import load_run
from nmt_engine.verify import node
from nmt_engine.verify.author import Post, author_gate
from nmt_engine.verify.gold import BATCH, _clip
from nmt_engine.verify.node_gold import NODE_BATCH

MIN_VOICES = 3
MIN_FAMILIES = 2
T2_MIN_DECISIVE = 5


@dataclass
class Receipt:
    source_id: str
    url: str
    family: str
    author_hash: str
    quote: str


@dataclass
class NodeStatus:
    node: str
    status: str  # supported / contradicted / unknown
    contested: bool = False
    supports: list[Receipt] = field(default_factory=list)
    contradicts: list[Receipt] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = {"node": self.node, "status": self.status, "contested": self.contested}
        for side in ("supports", "contradicts"):
            rs = getattr(self, side)
            d[side] = {
                "voices": len({r.author_hash for r in rs}),
                "families": sorted({r.family for r in rs}),
                "receipts": [r.__dict__ for r in rs],
            }
        return d


def _meets(rs: list[Receipt]) -> bool:
    return (
        len({r.author_hash for r in rs}) >= MIN_VOICES
        and len({r.family for r in rs}) >= MIN_FAMILIES
    )


def _one_per_author(rs: list[Receipt]) -> list[Receipt]:
    seen: dict[str, Receipt] = {}
    for r in sorted(rs, key=lambda r: r.source_id):
        seen.setdefault(r.author_hash, r)
    return list(seen.values())


def node_status(records: Sequence[dict], node_ids: Sequence[str]) -> list[NodeStatus]:
    """`records`: one per verified post with source_id, url, family, author_hash, role,
    names_solution and `nodes` {id: {verdict, quote}}. Only qualifying voices count."""
    out = []
    for nid in node_ids:
        sides: dict[str, list[Receipt]] = {"supports": [], "contradicts": []}
        for r in records:
            if not (
                r.get("role") == "USER"
                and r.get("names_solution")
                and r.get("family") in CUSTOMER_VOICE
                and r.get("author_hash")
                and not r.get("simulated")
            ):
                continue
            a = (r.get("nodes") or {}).get(nid)
            if a and a["verdict"] in sides and a.get("quote"):
                sides[a["verdict"]].append(
                    Receipt(r["source_id"], r["url"], r["family"], r["author_hash"], a["quote"])
                )
        sup, con = (_one_per_author(sides[k]) for k in ("supports", "contradicts"))
        s_ok, c_ok = _meets(sup), _meets(con)
        status = (
            "supported" if s_ok and not c_ok else "contradicted" if c_ok and not s_ok else "unknown"
        )
        out.append(NodeStatus(nid, status, s_ok and c_ok, sup, con))
    return out


def public(s: NodeStatus) -> dict:
    """Status for git: receipts as source ids and URLs; quotes stay in the run dir (§8 A9)."""
    d = s.as_dict()
    for side in ("supports", "contradicts"):
        d[side]["receipts"] = [
            {k: r[k] for k in ("source_id", "url", "family")} for r in d[side]["receipts"]
        ]
    return d


def t2(statuses: Sequence[NodeStatus]) -> dict:
    decisive = [s.node for s in statuses if s.status in ("supported", "contradicted")]
    return {
        "decisive": decisive,
        "n_decisive": len(decisive),
        "of": len(statuses),
        "min": T2_MIN_DECISIVE,
        "passed": len(decisive) >= T2_MIN_DECISIVE,
    }


def verify_run(
    llm: LLM, run_dir: Path, stmts: dict[str, str], category: str = "invoicing"
) -> list[dict]:
    """Producer author gate on every customer-voice post of the harvest, then the node check on
    USER posts naming a Solution. Writes `verified.jsonl` (gitignored run dir)."""
    run_dir = Path(run_dir)
    srcs = sorted(
        (
            s
            for s in load_run(run_dir).sources.values()
            if not s.retracted and s.customer_voice and collector_on(s.platform, {})
        ),
        key=lambda s: s.id,
    )
    posts = [Post(s.id, category, _clip((run_dir / s.text_path).read_text("utf-8"))) for s in srcs]
    authors = author_gate(llm, posts, "verify.author", BATCH)
    keep = [i for i, a in enumerate(authors) if a and a.continues]
    checks = node.node_check(llm, [posts[i] for i in keep], stmts, "verify.node", NODE_BATCH)
    by_post = dict(zip(keep, checks, strict=True))
    records = []
    for i, (s, a) in enumerate(zip(srcs, authors, strict=True)):
        records.append(
            {
                "source_id": s.id,
                "url": s.url,
                "platform": s.platform,
                "family": s.evidence_family,
                "author_hash": s.author_hash,
                "role": a.role if a else None,
                "names_solution": a.names_solution if a else None,
                "solution": a.solution if a else None,
                "nodes": by_post.get(i),
            }
        )
    with (run_dir / "verified.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    return records
