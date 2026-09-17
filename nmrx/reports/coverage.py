"""Coverage and missingness reporting.

Two different questions, deliberately answered separately:

**Source coverage** -- across the 50-entry registry, what do we have routes and rights for,
and where is the NMR evidence actually assigned and condition-complete?

**Record missingness** -- for records we have actually parsed, which fields are missing and
which calibration rules rejected them. The map insists on distinguishing *fields omitted by
an export or parser* from *fields genuinely absent upstream*, so every missingness row
carries an ``attribution`` that starts at ``unattributed`` and is only narrowed by evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from ..model.calibration import Eligibility, evaluate, rule_catalogue
from ..model.records import NMRRecord
from ..sources.registry import Source, SourceRegistry

#: Why a field is missing. Starts unattributed -- guessing here is how a parser bug gets
#: blamed on the upstream database, or vice versa.
ATTRIBUTIONS = (
    "unattributed",          # not yet investigated
    "absent_upstream",       # confirmed: the source record itself has no such field
    "omitted_by_export",     # the bulk export/format drops it though the source holds it
    "omitted_by_parser",     # our mapping does not read a field that is present
    "access_blocked",        # we could not fetch the part of the record that carries it
)


@dataclass
class MissingField:
    field: str
    count: int
    attribution: str = "unattributed"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "count": self.count,
            "attribution": self.attribution,
            "note": self.note,
        }


def source_coverage(registry: SourceRegistry) -> dict:
    """What the registry says we can and cannot do, per tier and overall."""
    nmr = registry.nmr_sources()
    measured = registry.measured_nmr_sources()

    def bucket(sources: Sequence[Source]) -> dict:
        return {
            "count": len(sources),
            "ids": [s.id for s in sources],
        }

    assigned_and_conditions = [
        s for s in measured if s.assignments in ("yes", "partial") and s.conditions in ("yes", "partial")
    ]

    return {
        "registry_size": len(registry),
        "by_tier": dict(Counter(s.tier for s in registry)),
        "by_status": dict(Counter(s.status for s in registry)),
        "by_rights_status": dict(Counter(s.rights_status for s in registry)),
        "by_harvest_policy": dict(Counter(s.harvest_policy for s in registry)),
        "by_commercial_use": dict(Counter(s.commercial_use for s in registry)),
        "nmr": {
            "any_nmr": bucket(nmr),
            "measured_nmr": bucket(measured),
            "measured_with_assignments_and_conditions": bucket(assigned_and_conditions),
            "assignments_yes": bucket([s for s in nmr if s.assignments == "yes"]),
            "conditions_yes": bucket([s for s in nmr if s.conditions == "yes"]),
        },
        "harvestable_now_if_network_opened": bucket(registry.harvestable()),
        "needs_credentials": bucket([s for s in registry if s.needs_credentials()]),
        "prohibited": bucket([s for s in registry if s.harvest_policy == "prohibited"]),
    }


def capability_matrix(registry: SourceRegistry, capabilities: Dict[str, dict]) -> List[dict]:
    """Join registry entries with per-source capability verdicts.

    ``capabilities`` maps ``source_id`` -> the five-question verdict dict. Sources with no
    assessment are reported as ``unassessed`` rather than dropped, so the matrix stays a
    complete picture of the registry.
    """
    rows: List[dict] = []
    for s in registry:
        cap = capabilities.get(s.id)
        rows.append({
            "source_id": s.id,
            "name": s.name,
            "tier": s.tier,
            "status": s.status,
            "has_nmr": s.has_nmr,
            "rights_status": s.rights_status,
            "harvest_policy": s.harvest_policy,
            "assessed": cap is not None,
            "capabilities": cap or {
                k: {"verdict": "unassessed", "evidence": ""}
                for k in ("find_structure", "retrieve_measurements",
                          "atom_assignments_and_conditions", "establish_rights",
                          "calibration_eligible")
            },
        })
    return rows


def record_missingness(records: Iterable[NMRRecord]) -> dict:
    """Aggregate what is missing across parsed records, and why they failed the gate."""
    records = list(records)
    field_counts: Counter = Counter()
    rule_counts: Counter = Counter()
    per_source_missing: Dict[str, Counter] = defaultdict(Counter)
    eligible = 0
    discovery_only = 0
    unusable = 0

    for rec in records:
        for f in rec.missing_metadata():
            field_counts[f] += 1
            per_source_missing[rec.source.source_id][f] += 1
        verdict: Eligibility = evaluate(rec)
        if verdict.eligible:
            eligible += 1
        elif verdict.discovery_usable:
            discovery_only += 1
        else:
            unusable += 1
        for rid in verdict.rule_ids:
            rule_counts[rid] += 1

    return {
        "record_count": len(records),
        "calibration_eligible": eligible,
        "discovery_only": discovery_only,
        "unusable": unusable,
        "missing_fields": [
            MissingField(field=f, count=c).to_dict()
            for f, c in field_counts.most_common()
        ],
        "rejections_by_rule": [
            {"rule_id": rid, "count": c,
             "statement": next((r["statement"] for r in rule_catalogue() if r["rule_id"] == rid), "")}
            for rid, c in rule_counts.most_common()
        ],
        "missing_fields_by_source": {
            sid: [MissingField(field=f, count=c).to_dict() for f, c in counter.most_common()]
            for sid, counter in sorted(per_source_missing.items())
        },
        "attribution_note": (
            "Every missing field starts 'unattributed'. Distinguishing a field the upstream "
            "record genuinely lacks from one our export or mapping dropped requires reading a "
            "real response, which is blocked until the hosts are allowed."
        ),
    }


def render_text(coverage: dict, missingness: Optional[dict] = None) -> str:
    """Compact human-readable summary. Intentionally plain -- it goes in a report."""
    lines: List[str] = []
    lines.append(f"Registry: {coverage['registry_size']} sources")
    lines.append("  tiers:  " + ", ".join(f"{k}={v}" for k, v in sorted(coverage["by_tier"].items())))
    lines.append("  status: " + ", ".join(f"{k}={v}" for k, v in sorted(coverage["by_status"].items())))
    lines.append("  rights: " + ", ".join(f"{k}={v}" for k, v in sorted(coverage["by_rights_status"].items())))
    nmr = coverage["nmr"]
    lines.append(f"NMR sources: {nmr['any_nmr']['count']} total, "
                 f"{nmr['measured_nmr']['count']} carry measured evidence")
    lines.append("  measured + assignments + conditions: "
                 + (", ".join(nmr["measured_with_assignments_and_conditions"]["ids"]) or "none"))
    lines.append(f"Harvestable if network opened: {coverage['harvestable_now_if_network_opened']['count']}")
    lines.append(f"Needs credentials: {coverage['needs_credentials']['count']}  |  "
                 f"Harvesting prohibited: {coverage['prohibited']['count']}")
    if missingness:
        lines.append("")
        lines.append(f"Records parsed: {missingness['record_count']} "
                     f"(calibration-eligible {missingness['calibration_eligible']}, "
                     f"discovery-only {missingness['discovery_only']}, "
                     f"unusable {missingness['unusable']})")
        for row in missingness["rejections_by_rule"][:10]:
            lines.append(f"  {row['rule_id']} x{row['count']}: {row['statement']}")
    return "\n".join(lines)
