"""Record types for molecules, NMR spectra and their source lineage.

Design rules taken directly from the source map:

* Experimental conditions that a source did not supply stay :data:`~nmrx.model.provenance.UNKNOWN`.
  Nothing in this module fills in a default solvent, temperature or reference.
* An atom assignment is a mapping onto a *specific structure*. ``MoleculeIdentity.atom_count``
  bounds the valid atom indices, so an assignment cannot silently refer to a different molecule.
* Every record carries its :class:`SourceRef` lineage. Deduplication collapses duplicates for
  counting purposes but never discards the source list -- see :mod:`nmrx.model.dedup`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .provenance import (
    UNKNOWN,
    EvidenceClass,
    IdentityMatch,
    Lineage,
    Provenanced,
    SpectrumState,
    is_known,
    unwrap,
)

#: A field that may be a real value, a provenance-stamped recovered value, or UNKNOWN.
Maybe = Union[Any, Provenanced, type(UNKNOWN)]

#: Nuclei NMRx currently reasons about. Extend deliberately -- a nucleus NMRx cannot
#: calibrate should be recorded, not silently coerced.
KNOWN_NUCLEI = ("1H", "13C", "15N", "19F", "31P", "11B", "29Si", "17O", "77Se", "195Pt")


@dataclass(frozen=True)
class MoleculeIdentity:
    """Exact chemical identity. Salts, tautomers and stereoisomers are NOT merged here."""

    inchikey: Maybe = UNKNOWN
    inchi: Maybe = UNKNOWN
    smiles: Maybe = UNKNOWN
    formula: Maybe = UNKNOWN
    net_charge: Maybe = UNKNOWN
    atom_count: Maybe = UNKNOWN
    name: Maybe = UNKNOWN
    external_ids: Dict[str, str] = field(default_factory=dict)

    def __hash__(self) -> int:
        """Hash on the structure keys only.

        ``external_ids`` is a dict, so the dataclass-generated hash raises. Identity is the
        structure, not which databases happen to have indexed it.
        """
        return hash((unwrap(self.inchikey), unwrap(self.smiles), unwrap(self.formula)))

    @property
    def skeleton_key(self) -> Optional[str]:
        """First InChIKey block -- the connectivity layer.

        Two molecules sharing this may still differ in stereochemistry, isotopes, charge or
        salt form, so a match here is :attr:`IdentityMatch.CONNECTIVITY_ONLY`, never exact.
        """
        key = unwrap(self.inchikey)
        if not isinstance(key, str) or "-" not in key:
            return None
        return key.split("-")[0]

    def compare(self, other: "MoleculeIdentity") -> IdentityMatch:
        """Classify how ``other`` relates to this molecule. Conservative by construction.

        Three distinct outcomes that must not be conflated: the same compound, a different
        form of the same skeleton, and a different compound entirely. Returning
        "connectivity only" for two molecules that share no connectivity would be a false
        claim of relatedness, so an unrelated pair says so, and an unpinned structure says
        the relationship is unknown rather than guessing one.
        """
        a, b = unwrap(self.inchikey), unwrap(other.inchikey)
        if not isinstance(a, str) or not isinstance(b, str):
            return IdentityMatch.UNKNOWN_RELATION
        if a == b:
            return IdentityMatch.EXACT
        if self.skeleton_key and self.skeleton_key == other.skeleton_key:
            # Same connectivity, different second block: stereo/isotope/protonation layer
            # differs. We cannot tell which from the key alone.
            return IdentityMatch.CONNECTIVITY_ONLY
        return IdentityMatch.UNRELATED


@dataclass(frozen=True)
class SourceRef:
    """Where one record came from, and under what terms."""

    source_id: str
    record_id: Maybe = UNKNOWN
    url: Maybe = UNKNOWN
    retrieved_at: Maybe = UNKNOWN
    licence: Maybe = UNKNOWN
    lineage: Lineage = Lineage.ORIGINAL_EXPERIMENT
    original_source_id: Optional[str] = None   # set when lineage is a mirror/reprocess

    def __post_init__(self) -> None:
        if self.lineage is not Lineage.ORIGINAL_EXPERIMENT and not self.original_source_id:
            raise ValueError(
                f"lineage {self.lineage.value!r} requires original_source_id so the "
                "originating experiment stays traceable"
            )

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "record_id": _plain(self.record_id),
            "url": _plain(self.url),
            "retrieved_at": _plain(self.retrieved_at),
            "licence": _plain(self.licence),
            "lineage": self.lineage.value,
            "original_source_id": self.original_source_id,
        }


@dataclass(frozen=True)
class ExperimentalConditions:
    """Acquisition conditions. Every field defaults to UNKNOWN on purpose."""

    solvent: Maybe = UNKNOWN
    temperature_k: Maybe = UNKNOWN
    reference_compound: Maybe = UNKNOWN
    spectrometer_frequency_mhz: Maybe = UNKNOWN
    ph: Maybe = UNKNOWN
    pulse_sequence: Maybe = UNKNOWN

    #: Conditions a record must carry to be considered condition-complete.
    REQUIRED_FOR_CALIBRATION = ("solvent", "temperature_k", "reference_compound")

    def missing_for_calibration(self) -> List[str]:
        return [f for f in self.REQUIRED_FOR_CALIBRATION if not is_known(getattr(self, f))]

    def is_calibration_complete(self) -> bool:
        return not self.missing_for_calibration()

    def to_dict(self) -> dict:
        return {
            f: _plain(getattr(self, f))
            for f in ("solvent", "temperature_k", "reference_compound",
                      "spectrometer_frequency_mhz", "ph", "pulse_sequence")
        }


@dataclass(frozen=True)
class ShiftAssignment:
    """One chemical shift tied to one atom index in the record's structure."""

    atom_index: Optional[int]      # None means the peak is not assigned to an atom
    element: str
    shift_ppm: float
    multiplicity: Maybe = UNKNOWN
    intensity: Maybe = UNKNOWN

    @property
    def is_assigned(self) -> bool:
        return self.atom_index is not None

    def to_dict(self) -> dict:
        return {
            "atom_index": self.atom_index,
            "element": self.element,
            "shift_ppm": self.shift_ppm,
            "multiplicity": _plain(self.multiplicity),
            "intensity": _plain(self.intensity),
        }


@dataclass
class NMRRecord:
    """One NMR spectrum from one source, with full provenance."""

    molecule: MoleculeIdentity
    source: SourceRef
    nucleus: Maybe = UNKNOWN
    evidence_class: EvidenceClass = EvidenceClass.MEASURED
    spectrum_state: SpectrumState = SpectrumState.UNASSIGNED_PEAKS
    identity_match: IdentityMatch = IdentityMatch.CONNECTIVITY_ONLY
    conditions: ExperimentalConditions = field(default_factory=ExperimentalConditions)
    shifts: List[ShiftAssignment] = field(default_factory=list)
    raw_file_urls: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # -- derived facts -------------------------------------------------------

    @property
    def assigned_shifts(self) -> List[ShiftAssignment]:
        return [s for s in self.shifts if s.is_assigned]

    @property
    def has_any_assignment(self) -> bool:
        return bool(self.assigned_shifts)

    @property
    def fully_assigned(self) -> bool:
        return bool(self.shifts) and all(s.is_assigned for s in self.shifts)

    def atom_index_problems(self) -> List[str]:
        """Atom indices that cannot be valid for this molecule."""
        problems: List[str] = []
        n = unwrap(self.molecule.atom_count)
        if not isinstance(n, int) and n is not UNKNOWN and n is not None:
            # A source may report the count as a string. Coerce rather than silently skip
            # the range check, which would let an out-of-range index through unnoticed.
            try:
                n = int(n)
            except (TypeError, ValueError):
                n = None
        seen: Dict[int, int] = {}
        for s in self.shifts:
            if s.atom_index is None:
                continue
            if s.atom_index < 0:
                problems.append(f"negative atom_index {s.atom_index}")
            if isinstance(n, int) and s.atom_index >= n:
                problems.append(
                    f"atom_index {s.atom_index} is outside the molecule's {n} atoms"
                )
            seen[s.atom_index] = seen.get(s.atom_index, 0) + 1
        for idx, count in seen.items():
            if count > 1:
                problems.append(f"atom_index {idx} assigned to {count} shifts")
        return problems

    def missing_metadata(self) -> List[str]:
        """Every field NMRx wanted and did not get. Drives the missingness report."""
        missing = list(self.conditions.missing_for_calibration())
        if not is_known(self.nucleus):
            missing.append("nucleus")
        if not is_known(self.molecule.inchikey):
            missing.append("molecule.inchikey")
        if not is_known(self.source.licence):
            missing.append("source.licence")
        if not self.has_any_assignment:
            missing.append("atom_assignments")
        return missing

    def to_dict(self) -> dict:
        return {
            "molecule": {
                "inchikey": _plain(self.molecule.inchikey),
                "smiles": _plain(self.molecule.smiles),
                "formula": _plain(self.molecule.formula),
                "atom_count": _plain(self.molecule.atom_count),
                "external_ids": dict(self.molecule.external_ids),
            },
            "source": self.source.to_dict(),
            "nucleus": _plain(self.nucleus),
            "evidence_class": self.evidence_class.value,
            "spectrum_state": self.spectrum_state.value,
            "identity_match": self.identity_match.value,
            "conditions": self.conditions.to_dict(),
            "shifts": [s.to_dict() for s in self.shifts],
            "raw_file_urls": list(self.raw_file_urls),
            "missing_metadata": self.missing_metadata(),
            "notes": list(self.notes),
        }


def _plain(v: Any) -> Any:
    """JSON-safe rendering that keeps UNKNOWN and provenance visible."""
    if v is UNKNOWN:
        return None
    if isinstance(v, Provenanced):
        return v.to_dict()
    return v
