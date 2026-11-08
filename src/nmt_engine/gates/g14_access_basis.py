"""Gate 14: every Source has an allowed access_basis; forbidden hosts need a licence."""

from urllib.parse import urlparse

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.schema import ALLOWED_ACCESS_BASIS
from nmt_engine.store import RunData


def forbidden_host(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h in host for h in hosts)


@gate(14, "access_basis", "Access basis present and allowed")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    for src in run.sources.values():
        if src.access_basis not in ALLOWED_ACCESS_BASIS:
            findings.append(
                Finding("source", src.id, f"access_basis {src.access_basis!r} not allowed", "drop")
            )
        elif forbidden_host(src.url, cfg.forbidden_hosts) and src.access_basis != "licensed":
            findings.append(
                Finding("source", src.id, f"forbidden host without licence: {src.url}", "drop")
            )
    return findings
