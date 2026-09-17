"""Turn probe results and policy state into a precise, actionable blocker list.

A blocker is only useful if it names the exact thing that has to change. Each entry here
carries the failing URL, the observed error, the layer that refused, and the one concrete
action that would unblock it -- and says plainly when that action is not ours to take.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..sources.policy import AccessPolicy, load_policy
from ..sources.registry import SourceRegistry, load_registry

PROBE_DIR = Path(__file__).resolve().parent.parent / "data" / "probes"

#: Which layer refused, and therefore who can fix it.
LAYERS = {
    "environment_network": (
        "Claude Code cloud environment -- Network access -> Custom -> Allowed domains",
        "the environment owner, in the environment settings; no code change helps",
    ),
    "project_policy": (
        "nmrx/data/access_policy.json",
        "add the host deliberately, with the smallest exact operation and an estimated byte count",
    ),
    "provider_rights": (
        "the data provider's licence or terms",
        "obtain the licence, account or written permission before any request",
    ),
    "provider_prohibition": (
        "the data provider's own no-robots policy",
        "cannot be resolved; use the source manually or not at all",
    ),
    "unconfirmed_schema": (
        "nmrx/adapters/mappings/<source>.json",
        "read a real response, fix the mapping, set schema_confirmed=true",
    ),
}


@dataclass
class Blocker:
    source_id: str
    host: Optional[str]
    layer: str
    what_failed: str
    observed: str
    action: str
    blocks: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        where, who = LAYERS.get(self.layer, ("unknown", "unknown"))
        return {
            "source_id": self.source_id,
            "host": self.host,
            "layer": self.layer,
            "setting_location": where,
            "resolved_by": who,
            "what_failed": self.what_failed,
            "observed": self.observed,
            "action": self.action,
            "blocks": list(self.blocks),
        }


def latest_probe(directory: Path | str = PROBE_DIR) -> Optional[dict]:
    directory = Path(directory)
    if not directory.exists():
        return None
    files = sorted(directory.glob("pilot_probe_*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def from_probe(report: dict) -> List[Blocker]:
    """One blocker per host the environment refused -- not one per attempted URL."""
    by_host: Dict[str, dict] = {}
    for row in report.get("results", []):
        if row["classification"] == "blocked_by_environment_network_policy":
            by_host.setdefault(row["host"], row)

    out: List[Blocker] = []
    for host, row in sorted(by_host.items()):
        out.append(Blocker(
            source_id=row["source_id"],
            host=host,
            layer="environment_network",
            what_failed=row["url"],
            observed=row.get("error") or "CONNECT refused with 403",
            action=(
                f"Add '{host}' to the environment's Allowed domains "
                "(Network access -> Custom, one hostname per line). Keep existing "
                "package-manager access. This is an environment setting; it cannot be "
                "changed from chat or from project code."
            ),
            blocks=[row["purpose"]],
        ))
    return out


def from_policy(policy: AccessPolicy, registry: SourceRegistry) -> List[Blocker]:
    """Blockers that exist even if every network door were open."""
    out: List[Blocker] = []

    for entry in policy.prohibited_hosts():
        out.append(Blocker(
            source_id=entry["source_id"],
            host=entry["host"],
            layer="provider_prohibition",
            what_failed="automated collection",
            observed=entry["reason"],
            action="Keep out of automated harvesting permanently. Manual reference only.",
            blocks=["any automated retrieval"],
        ))

    for source in registry:
        blocker = policy.credential_blocker(source.id)
        if blocker:
            out.append(Blocker(
                source_id=source.id,
                host=(source.hosts("api") or source.hosts("web") or [None])[0],
                layer="provider_rights",
                what_failed="access without credentials or a licence",
                observed=blocker,
                action=(
                    f"Obtain {blocker} before adding a host for {source.id}. "
                    "Do not implement an adapter first."
                ),
                blocks=["retrieval", "redistribution"],
            ))

    for source in registry:
        if source.rights_status in ("unverified", "open_unverified") and source.has_nmr:
            evidence = source.raw["rights"].get("evidence_link") or "the provider's licence page"
            out.append(Blocker(
                source_id=source.id,
                host=None,
                layer="provider_rights",
                what_failed="establishing reuse rights",
                observed=f"rights.status is {source.rights_status}; licence text not confirmed",
                action=f"Read {evidence} on the exact data release and record the licence verbatim.",
                blocks=["calibration export (CAL-008)", "redistribution"],
            ))

    return out


def build(probe: Optional[dict] = None,
          policy: Optional[AccessPolicy] = None,
          registry: Optional[SourceRegistry] = None) -> dict:
    policy = policy or load_policy()
    registry = registry or load_registry()
    probe = probe if probe is not None else latest_probe()

    network = from_probe(probe) if probe else []
    other = from_policy(policy, registry)

    return {
        "probe_run_at": probe.get("run_at") if probe else None,
        "bytes_downloaded_in_probe": probe.get("total_bytes_downloaded") if probe else None,
        "blocker_count": len(network) + len(other),
        "by_layer": _counts(network + other),
        "network_blockers": [b.to_dict() for b in network],
        "rights_and_policy_blockers": [b.to_dict() for b in other],
    }


def _counts(blockers: Sequence[Blocker]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for b in blockers:
        out[b.layer] = out.get(b.layer, 0) + 1
    return out


def render_text(report: dict) -> str:
    lines: List[str] = []
    if report["probe_run_at"]:
        lines.append(f"Probe {report['probe_run_at']} downloaded "
                     f"{report['bytes_downloaded_in_probe']} bytes.")
    lines.append("")
    if report["network_blockers"]:
        lines.append("BLOCKED BY THE ENVIRONMENT'S NETWORK SETTING "
                     "(no code change can fix these):")
        for b in report["network_blockers"]:
            lines.append(f"  {b['host']}")
            lines.append(f"    tried:    {b['what_failed']}")
            lines.append(f"    observed: {b['observed']}")
        lines.append("")
        lines.append("  Fix: environment settings -> Network access -> Custom -> Allowed domains,")
        lines.append("       one hostname per line. Keep package-manager access.")
        lines.append("")
    rights = [b for b in report["rights_and_policy_blockers"]
              if b["layer"] == "provider_rights"]
    prohibited = [b for b in report["rights_and_policy_blockers"]
                  if b["layer"] == "provider_prohibition"]
    if prohibited:
        lines.append("PERMANENTLY OUT OF AUTOMATED HARVESTING:")
        for b in prohibited:
            lines.append(f"  {b['source_id']} ({b['host']}): {b['observed']}")
        lines.append("")
    if rights:
        lines.append(f"RIGHTS NOT ESTABLISHED ({len(rights)}):")
        for b in rights:
            lines.append(f"  {b['source_id']:<18} {b['observed']}")
    return "\n".join(lines)
