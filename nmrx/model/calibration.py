"""The strict NMR calibration eligibility gate.

The map draws a hard line that this module enforces:

    "Retain incomplete records for discovery where appropriate, but keep them out of strict
    calibration exports until they meet the declared criteria. Do not invent missing solvent,
    temperature or reference values."

So a record has *two* independent verdicts:

``eligible``
    may enter a strict calibration export. Every rule below passed.
``discovery_usable``
    may be shown in a dossier as source-attributed context, clearly labelled, even though it
    failed one or more calibration rules.

A record is never silently upgraded. Each failure carries a stable ``rule_id`` and a fixed
rejection string, so the missingness report can aggregate reasons across thousands of records
and a beginner can read exactly why a spectrum did not qualify.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from .provenance import (
    EvidenceClass,
    IdentityMatch,
    Lineage,
    is_known,
    unwrap,
)
from .records import KNOWN_NUCLEI, NMRRecord


@dataclass(frozen=True)
class Rejection:
    rule_id: str
    reason: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.rule_id}: {self.reason}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class Eligibility:
    """Outcome of running the gate over one record."""

    eligible: bool
    rejections: List[Rejection] = field(default_factory=list)
    discovery_usable: bool = True
    discovery_block: Optional[Rejection] = None

    @property
    def rule_ids(self) -> List[str]:
        return [r.rule_id for r in self.rejections]

    def to_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "discovery_usable": self.discovery_usable,
            "discovery_block": None if self.discovery_block is None else {
                "rule_id": self.discovery_block.rule_id,
                "reason": self.discovery_block.reason,
                "detail": self.discovery_block.detail,
            },
            "rejections": [
                {"rule_id": r.rule_id, "reason": r.reason, "detail": r.detail}
                for r in self.rejections
            ],
        }


#: A rule returns None when it passes, or a Rejection when it fails.
Rule = Callable[[NMRRecord], Optional[Rejection]]


# --- rules ------------------------------------------------------------------
# Ordered weakest-precondition first so the rejection list reads top-down.

def _cal_001_measured(rec: NMRRecord) -> Optional[Rejection]:
    if rec.evidence_class is not EvidenceClass.MEASURED:
        return Rejection(
            "CAL-001",
            "not an experimental measurement",
            f"evidence_class is {rec.evidence_class.value}; calculated, predicted and "
            "literature-extracted values must stay distinguishable and out of strict calibration",
        )
    return None


def _cal_002_exact_identity(rec: NMRRecord) -> Optional[Rejection]:
    if rec.identity_match is not IdentityMatch.EXACT:
        return Rejection(
            "CAL-002",
            "not the exact submitted molecule",
            f"identity_match is {rec.identity_match.value}; a related compound can inform a "
            "comparison but cannot be presented as a measurement of the submitted molecule",
        )
    return None


def _cal_003_original_experiment(rec: NMRRecord) -> Optional[Rejection]:
    if not rec.source.lineage.is_independent_evidence:
        return Rejection(
            "CAL-003",
            "not the original experiment",
            f"lineage is {rec.source.lineage.value} of "
            f"{rec.source.original_source_id!r}; a mirrored copy is not independent evidence",
        )
    return None


def _cal_004_nucleus(rec: NMRRecord) -> Optional[Rejection]:
    nucleus = unwrap(rec.nucleus)
    if not is_known(rec.nucleus):
        return Rejection("CAL-004", "nucleus unknown", "the source did not state the observed nucleus")
    if nucleus not in KNOWN_NUCLEI:
        return Rejection(
            "CAL-004",
            "nucleus not supported",
            f"{nucleus!r} is outside NMRx's recognised nuclei {KNOWN_NUCLEI}",
        )
    return None


def _cal_005_conditions(rec: NMRRecord) -> Optional[Rejection]:
    missing = rec.conditions.missing_for_calibration()
    if missing:
        return Rejection(
            "CAL-005",
            "experimental conditions incomplete",
            "missing " + ", ".join(missing) + "; these must not be invented",
        )
    return None


def _cal_006_assignments(rec: NMRRecord) -> Optional[Rejection]:
    if not rec.shifts:
        return Rejection("CAL-006", "no shift values", "record carries no numerical shifts")
    if not rec.spectrum_state.has_numeric_values:
        return Rejection(
            "CAL-006",
            "no numerical spectrum",
            f"spectrum_state is {rec.spectrum_state.value}",
        )
    if not rec.fully_assigned:
        n_assigned = len(rec.assigned_shifts)
        return Rejection(
            "CAL-006",
            "atom assignments incomplete",
            f"{n_assigned} of {len(rec.shifts)} shifts carry an atom index; strict calibration "
            "needs a complete atom mapping",
        )
    return None


def _cal_007_atom_mapping_integrity(rec: NMRRecord) -> Optional[Rejection]:
    problems = rec.atom_index_problems()
    if problems:
        return Rejection("CAL-007", "atom mapping invalid", "; ".join(problems))
    return None


def _cal_008_licence_known(rec: NMRRecord) -> Optional[Rejection]:
    if not is_known(rec.source.licence):
        return Rejection(
            "CAL-008",
            "source rights not established",
            f"no licence recorded for {rec.source.source_id}/{unwrap(rec.source.record_id)!r}; "
            "rights must be checked on the exact data, not inferred from the host",
        )
    return None


def _cal_009_identifier(rec: NMRRecord) -> Optional[Rejection]:
    if not is_known(rec.molecule.inchikey):
        return Rejection(
            "CAL-009",
            "molecule identity not pinned",
            "no InChIKey; without an exact structure key the atom mapping cannot be trusted",
        )
    return None


#: The ordered strict-calibration rule set.
CALIBRATION_RULES: Tuple[Rule, ...] = (
    _cal_001_measured,
    _cal_002_exact_identity,
    _cal_003_original_experiment,
    _cal_004_nucleus,
    _cal_005_conditions,
    _cal_006_assignments,
    _cal_007_atom_mapping_integrity,
    _cal_008_licence_known,
    _cal_009_identifier,
)

#: Rules that also block *discovery* use. A record failing only calibration rules is still
#: worth showing as labelled context; a record failing these is not safe to show at all.
DISCOVERY_BLOCKING_RULES: Tuple[Rule, ...] = (
    _cal_007_atom_mapping_integrity,   # an invalid mapping is wrong, not merely incomplete
)


def evaluate(rec: NMRRecord, rules: Sequence[Rule] = CALIBRATION_RULES) -> Eligibility:
    """Run the gate. Collects *all* failures rather than stopping at the first."""
    rejections = [r for r in (rule(rec) for rule in rules) if r is not None]
    discovery_block = next(
        (r for rule in DISCOVERY_BLOCKING_RULES for r in [rule(rec)] if r is not None),
        None,
    )
    return Eligibility(
        eligible=not rejections,
        rejections=rejections,
        discovery_usable=discovery_block is None,
        discovery_block=discovery_block,
    )


def rule_catalogue() -> List[dict]:
    """Machine-readable description of every rule, for docs and the coverage report."""
    return [
        {"rule_id": "CAL-001", "statement": "evidence_class must be measured",
         "rejects_with": "not an experimental measurement"},
        {"rule_id": "CAL-002", "statement": "identity_match must be exact",
         "rejects_with": "not the exact submitted molecule"},
        {"rule_id": "CAL-003", "statement": "lineage must be the original experiment",
         "rejects_with": "not the original experiment"},
        {"rule_id": "CAL-004", "statement": "nucleus must be known and recognised",
         "rejects_with": "nucleus unknown / nucleus not supported"},
        {"rule_id": "CAL-005", "statement": "solvent, temperature and reference must all be present",
         "rejects_with": "experimental conditions incomplete"},
        {"rule_id": "CAL-006", "statement": "every shift must carry an atom index",
         "rejects_with": "atom assignments incomplete / no shift values"},
        {"rule_id": "CAL-007", "statement": "atom indices must be in range and unique",
         "rejects_with": "atom mapping invalid"},
        {"rule_id": "CAL-008", "statement": "the record's licence must be recorded",
         "rejects_with": "source rights not established"},
        {"rule_id": "CAL-009", "statement": "the molecule must carry an InChIKey",
         "rejects_with": "molecule identity not pinned"},
    ]
