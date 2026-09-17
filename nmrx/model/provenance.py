"""Provenance vocabulary for NMRx records.

The source map is explicit that four distinctions must be stored *independently* and must
never be collapsed:

============================  ==========================================================
axis                          values
============================  ==========================================================
:class:`EvidenceClass`        measured / quantum calculated / model predicted /
                              literature extracted
:class:`SpectrumState`        raw / processed / unassigned peaks / assigned peaks /
                              image only
:class:`Lineage`              original experiment / mirrored copy / reprocessed version
:class:`IdentityMatch`        exact molecule / different protonation, salt, tautomer,
                              isotope or stereoisomer
============================  ==========================================================

Two further rules are enforced by the types here rather than by convention:

* **Unknown stays unknown.** :data:`UNKNOWN` is a distinct sentinel, not ``None`` and not a
  default value. A missing solvent is never silently filled in.
* **Recovery is stamped.** If a solvent, temperature or reference is later recovered from a
  paper or a documented database convention, it is wrapped in :class:`Provenanced` recording
  where it came from. It never becomes indistinguishable from a value the source supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar


class EvidenceClass(str, Enum):
    """How a number came to exist. Never merge these."""

    MEASURED = "measured"
    QUANTUM_CALCULATED = "quantum_calculated"
    MODEL_PREDICTED = "model_predicted"
    LITERATURE_EXTRACTED = "literature_extracted"

    @property
    def is_experimental(self) -> bool:
        return self is EvidenceClass.MEASURED


class SpectrumState(str, Enum):
    """How far a spectrum has been processed, and whether atoms are assigned."""

    RAW = "raw"
    PROCESSED = "processed"
    UNASSIGNED_PEAKS = "unassigned_peaks"
    ASSIGNED_PEAKS = "assigned_peaks"
    IMAGE_ONLY = "image_only"

    @property
    def has_atom_assignments(self) -> bool:
        return self is SpectrumState.ASSIGNED_PEAKS

    @property
    def has_numeric_values(self) -> bool:
        return self is not SpectrumState.IMAGE_ONLY


class Lineage(str, Enum):
    """Whether this record is the experiment, a copy of it, or a rework of it."""

    ORIGINAL_EXPERIMENT = "original_experiment"
    MIRRORED_COPY = "mirrored_copy"
    REPROCESSED_VERSION = "reprocessed_version"

    @property
    def is_independent_evidence(self) -> bool:
        """A mirror of one experiment is not a second supporting result."""
        return self is Lineage.ORIGINAL_EXPERIMENT


class IdentityMatch(str, Enum):
    """How the source record's molecule relates to the submitted molecule."""

    EXACT = "exact"
    DIFFERENT_PROTONATION = "different_protonation"
    DIFFERENT_SALT = "different_salt"
    DIFFERENT_TAUTOMER = "different_tautomer"
    DIFFERENT_ISOTOPE = "different_isotope"
    DIFFERENT_STEREOISOMER = "different_stereoisomer"
    CONNECTIVITY_ONLY = "connectivity_only"

    @property
    def is_exact(self) -> bool:
        return self is IdentityMatch.EXACT


class FieldStatus(str, Enum):
    """Per-field outcome in a molecule dossier.

    The map requires every dossier field to carry one of these rather than being silently
    absent, so "we did not look" and "it does not exist" never look the same.
    """

    FOUND = "found"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    ACCESS_BLOCKED = "access_blocked"
    RIGHTS_REVIEW_NEEDED = "rights_review_needed"
    CALCULATION_FAILED = "calculation_failed"


class ValueOrigin(str, Enum):
    """Where a stored value came from -- never inferred, always recorded."""

    SOURCE_RECORD = "source_record"
    RECOVERED_FROM_PUBLICATION = "recovered_from_publication"
    DATABASE_CONVENTION = "database_convention"
    USER_SUPPLIED = "user_supplied"
    COMPUTED_BY_NMRX = "computed_by_nmrx"


class _Unknown:
    """Sentinel for 'this source did not tell us'.

    Distinct from ``None`` (which would read as "no value") and from any default. Falsy so
    ``if record.solvent:`` behaves sensibly, but never equal to anything but itself.
    """

    _instance: Optional["_Unknown"] = None

    def __new__(cls) -> "_Unknown":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __str__(self) -> str:
        return "unknown"

    def __eq__(self, other: object) -> bool:
        return other is self

    def __hash__(self) -> int:
        return hash("nmrx.UNKNOWN")

    def __reduce__(self):
        return (_Unknown, ())


#: The single unknown sentinel. Import and compare with ``is``.
UNKNOWN = _Unknown()


T = TypeVar("T")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Provenanced(Generic[T]):
    """A value plus the record of how NMRx came to hold it.

    Used for any field that might be recovered after the fact. The map is explicit: a
    reference or condition recovered from a paper or a documented database convention must
    carry that derivation, and must not be presented as if the source record supplied it.
    """

    value: T
    origin: ValueOrigin
    evidence: Optional[str] = None      # DOI, URL, or the convention being relied on
    note: Optional[str] = None
    recorded_at: str = field(default_factory=_utcnow)

    @property
    def is_from_source(self) -> bool:
        return self.origin is ValueOrigin.SOURCE_RECORD

    @property
    def is_recovered(self) -> bool:
        return self.origin in (
            ValueOrigin.RECOVERED_FROM_PUBLICATION,
            ValueOrigin.DATABASE_CONVENTION,
        )

    def __post_init__(self) -> None:
        if self.is_recovered and not self.evidence:
            raise ValueError(
                f"a value with origin {self.origin.value!r} must carry evidence "
                "(a DOI, URL or the named convention); recovery without a citation is "
                "indistinguishable from invention"
            )

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "origin": self.origin.value,
            "evidence": self.evidence,
            "note": self.note,
            "recorded_at": self.recorded_at,
        }


def unwrap(v: Any) -> Any:
    """Return the underlying value of a :class:`Provenanced`, or ``v`` unchanged."""
    return v.value if isinstance(v, Provenanced) else v


def is_known(v: Any) -> bool:
    """True when ``v`` carries an actual value (not UNKNOWN, not None)."""
    inner = unwrap(v)
    return inner is not UNKNOWN and inner is not None
