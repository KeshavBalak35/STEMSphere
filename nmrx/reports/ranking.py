"""Rank candidate connectors by how much useful NMR data they would actually add.

The ranking is computed from registry fields and recorded capability verdicts, not asserted,
so the reasoning is inspectable and moves when the evidence moves. Every component is
printed alongside the score.

The weighting encodes NMRx's actual priority, which is *calibration-grade* NMR:
a source with assigned atoms and stated conditions is worth far more than a large source
without them, and a source whose rights cannot be established is capped, because a record
with no recorded licence fails the calibration gate at CAL-008 no matter how good its data is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..sources.policy import AccessPolicy, load_policy
from ..sources.registry import Source, SourceRegistry, load_registry

#: verdict -> score. "unknown" scores below "partial": an unverified claim is not a feature.
VERDICT_SCORE = {"yes": 1.0, "partial": 0.5, "unknown": 0.15, "no": 0.0, "unassessed": 0.1}

RIGHTS_SCORE = {
    "open_verified": 1.0,
    "per_record": 0.6,       # workable, but must be read per record
    "open_unverified": 0.4,
    "unverified": 0.2,
    "non_commercial": 0.05,
    "licensed_required": 0.0,
}

WEIGHTS = {
    "measured_nmr": 3.0,        # does it hold measured NMR at all
    "assignments": 3.0,         # atom assignments -- the scarcest thing
    "conditions": 2.5,          # solvent / temperature / reference
    "rights": 2.0,              # can we establish usable rights
    "retrievability": 1.5,      # can we actually pull numbers or files
    "access_simplicity": 1.0,   # no key, no account, no licence
}


@dataclass
class Ranked:
    source_id: str
    name: str
    score: float
    components: Dict[str, float] = field(default_factory=dict)
    adds: str = ""
    costs: List[str] = field(default_factory=list)
    hosts_to_open: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "score": round(self.score, 2),
            "components": {k: round(v, 2) for k, v in self.components.items()},
            "adds": self.adds,
            "costs": list(self.costs),
            "hosts_to_open": list(self.hosts_to_open),
        }


def _access_simplicity(source: Source) -> float:
    auth = source.raw.get("access", {}).get("auth", "unknown")
    return {"none": 1.0, "unknown": 0.4, "api_key": 0.3, "account": 0.2, "license": 0.0}.get(auth, 0.3)


def score_source(
    source: Source,
    capabilities: Optional[dict] = None,
    policy: Optional[AccessPolicy] = None,
) -> Ranked:
    caps = capabilities or {}

    def verdict(key: str, fallback: str) -> float:
        v = caps.get(key)
        if isinstance(v, dict):
            v = v.get("verdict")
        return VERDICT_SCORE.get(v or fallback, 0.15)

    components = {
        "measured_nmr": 1.0 if (source.has_nmr and "measured" in source.evidence_types) else 0.0,
        "assignments": VERDICT_SCORE.get(source.assignments, 0.15),
        "conditions": VERDICT_SCORE.get(source.conditions, 0.15),
        "rights": RIGHTS_SCORE.get(source.rights_status, 0.2),
        "retrievability": verdict("retrieve_measurements", "unknown"),
        "access_simplicity": _access_simplicity(source),
    }

    score = sum(WEIGHTS[k] * v for k, v in components.items())

    costs: List[str] = []
    if source.harvest_policy == "prohibited":
        costs.append("provider prohibits automated collection -- excluded entirely")
        score = 0.0
    if source.harvest_policy == "licence_required":
        costs.append("needs a licence or paid agreement before any request")
        score = min(score, 2.0)
    if source.rights_status in ("unverified", "open_unverified"):
        costs.append("licence text unread -- every record fails the calibration gate at CAL-008 "
                     "until the rights are established")
    if source.needs_credentials():
        costs.append(f"authentication required ({source.raw['access']['auth']})")

    hosts = source.hosts("api") or source.hosts("web")
    if policy:
        granted = {g.host for g in policy.granted_hosts()}
        hosts = [h for h in hosts if h not in granted]

    return Ranked(
        source_id=source.id,
        name=source.name,
        score=score,
        components=components,
        adds=source.raw.get("nmr_relevance", {}).get("note", "") or source.raw.get("value", "")[:180],
        costs=costs,
        hosts_to_open=hosts,
    )


def rank_next_connectors(
    registry: Optional[SourceRegistry] = None,
    capabilities: Optional[Dict[str, dict]] = None,
    policy: Optional[AccessPolicy] = None,
    *,
    nmr_only: bool = True,
    exclude_granted: bool = True,
    limit: Optional[int] = None,
) -> List[Ranked]:
    """Rank sources NMRx has not yet connected, best first."""
    registry = registry or load_registry()
    policy = policy or load_policy()
    capabilities = capabilities or {}

    granted_sources = {g.source_id for g in policy.granted_hosts()}
    candidates: List[Source] = []
    for source in registry:
        if nmr_only and not source.has_nmr:
            continue
        if exclude_granted and source.id in granted_sources:
            continue
        if source.harvest_policy == "prohibited":
            continue
        candidates.append(source)

    ranked = [score_source(s, capabilities.get(s.id), policy) for s in candidates]
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:limit] if limit else ranked


def render_text(ranked: Sequence[Ranked]) -> str:
    lines: List[str] = []
    for i, r in enumerate(ranked, 1):
        lines.append(f"{i}. {r.name}  ({r.source_id})   score {r.score:.2f}")
        parts = " ".join(f"{k}={v:.2f}" for k, v in r.components.items())
        lines.append(f"     {parts}")
        if r.adds:
            lines.append(f"     adds:  {r.adds}")
        if r.hosts_to_open:
            lines.append(f"     hosts: {', '.join(r.hosts_to_open)}")
        for c in r.costs:
            lines.append(f"     cost:  {c}")
        lines.append("")
    return "\n".join(lines)
