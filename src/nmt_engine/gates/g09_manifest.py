"""Gate 9: frozen inputs still match the hashes recorded in run_manifest.json."""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData
from nmt_engine.util import canonical_json, sha256_file, sha256_text


def manifest_hash(frozen) -> str:
    return sha256_text(canonical_json(sorted((f.path, f.sha256) for f in frozen)))


@gate(9, "manifest", "Freeze manifest hash check")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    m = run.manifest
    if m is None:
        return [Finding("run", str(run.run_dir.name), "run_manifest.json missing")]
    findings: list[Finding] = []
    if m.manifest_sha256 != manifest_hash(m.frozen):
        findings.append(Finding("run", m.run_id, "manifest_sha256 does not match frozen list"))
    root = run.run_dir.resolve()
    for f in m.frozen:
        path = (run.run_dir / f.path).resolve()
        if not path.is_relative_to(root):
            findings.append(Finding("run", m.run_id, f"frozen path {f.path} is outside the run"))
        elif not path.is_file():
            findings.append(Finding("run", m.run_id, f"frozen file {f.path} missing"))
        elif sha256_file(path) != f.sha256:
            findings.append(Finding("run", m.run_id, f"frozen file {f.path} changed"))
    return findings
