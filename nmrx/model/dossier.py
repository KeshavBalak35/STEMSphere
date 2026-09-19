"""The per-molecule dossier.

The source map states the coverage goal directly: for a submitted molecule, produce

* an exact-identity section and *separately labelled* related structures;
* source-attributed measured NMR/IR when available;
* NMRx calculations with method, limitations and job provenance;
* protein targets, distinct measured assay values and structure links;
* and **a clear status for each field**: found, not found, unsupported, access blocked,
  rights review needed, or calculation failed.

That last requirement is why every section here carries a :class:`FieldStatus` instead of
being silently absent. "We did not look", "it does not exist" and "we were blocked" are three
different answers, and a dossier that cannot tell them apart is misleading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .calibration import evaluate
from .dedup import ExperimentCluster, cluster_records
from .provenance import UNKNOWN, FieldStatus, IdentityMatch, Provenanced, unwrap
from .records import MoleculeIdentity, NMRRecord


def _plain(v):
    """JSON-safe rendering. UNKNOWN becomes null; provenance is kept, not flattened."""
    if v is UNKNOWN:
        return None
    if isinstance(v, Provenanced):
        return v.to_dict()
    return v


@dataclass
class Section:
    """One dossier field with an explicit status and its supporting evidence."""

    name: str
    status: FieldStatus
    detail: str = ""
    evidence: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass
class MoleculeDossier:
    """Everything NMRx can say about one submitted molecule, with each claim's status."""

    submitted: MoleculeIdentity
    sections: List[Section] = field(default_factory=list)

    def add(self, section: Section) -> Section:
        self.sections.append(section)
        return section

    def section(self, name: str) -> Optional[Section]:
        return next((s for s in self.sections if s.name == name), None)

    def status_summary(self) -> Dict[str, str]:
        return {s.name: s.status.value for s in self.sections}

    def to_dict(self) -> dict:
        return {
            "submitted_molecule": {
                "inchikey": _plain(unwrap(self.submitted.inchikey)),
                "smiles": _plain(unwrap(self.submitted.smiles)),
                "formula": _plain(unwrap(self.submitted.formula)),
            },
            "sections": [s.to_dict() for s in self.sections],
            "status_summary": self.status_summary(),
        }


@dataclass(frozen=True)
class IdentityVerdict:
    """The result of *computing* how one record relates to the submitted molecule."""

    record: NMRRecord
    computed: IdentityMatch
    claimed: IdentityMatch
    #: True when the record asserted a relationship the structures do not support.
    disagrees: bool

    @property
    def is_exact(self) -> bool:
        return self.computed is IdentityMatch.EXACT

    @property
    def is_verifiable(self) -> bool:
        return self.computed is not IdentityMatch.UNKNOWN_RELATION


def classify_identity(submitted: MoleculeIdentity,
                      records: Sequence[NMRRecord]) -> List[IdentityVerdict]:
    """Compute each record's relationship to the submitted molecule.

    The record's own ``identity_match`` is treated as a *claim*, not as the answer. It
    arrives from an adapter mapping whose schema nobody has confirmed, so a source (or a
    mapping bug) asserting "exact" must not be enough to place a spectrum in the exact
    bucket of a dossier. The structures are compared here and the computed verdict wins;
    a disagreement is recorded so it is visible rather than silently overridden.
    """
    out: List[IdentityVerdict] = []
    for rec in records:
        computed = submitted.compare(rec.molecule)
        claimed = rec.identity_match
        # A claim only "disagrees" when both sides actually say something.
        disagrees = (
            computed is not claimed
            and computed is not IdentityMatch.UNKNOWN_RELATION
            and claimed is not IdentityMatch.UNKNOWN_RELATION
        )
        out.append(IdentityVerdict(record=rec, computed=computed,
                                   claimed=claimed, disagrees=disagrees))
    return out


def _split_by_identity(submitted: MoleculeIdentity,
                       records: Sequence[NMRRecord]) -> tuple:
    """Exact / related / unverifiable, decided by comparing structures.

    Three buckets, not two. A record whose identity cannot be computed -- because the
    submitted molecule or the record itself carries no InChIKey -- is neither exact nor
    related. Filing it under "related" would assert a relationship nobody established.
    """
    verdicts = classify_identity(submitted, records)
    exact = [v.record for v in verdicts if v.is_exact]
    related = [v.record for v in verdicts
               if not v.is_exact and v.is_verifiable and v.computed.is_related]
    unrelated = [v.record for v in verdicts if v.computed is IdentityMatch.UNRELATED]
    unverifiable = [v.record for v in verdicts if not v.is_verifiable]
    disagreements = [v for v in verdicts if v.disagrees]
    return exact, related, unrelated, unverifiable, disagreements


def _cluster_evidence(clusters: Sequence[ExperimentCluster],
                      computed_by_record: Optional[dict] = None) -> List[dict]:
    """Render clusters as dossier evidence.

    Clusters whose primary record the gate marked *not* discovery-usable are dropped
    entirely: an atom mapping that is actually wrong (an index outside the molecule, two
    shifts claiming one atom) is not incomplete data to show with a caveat, it is incorrect
    data. Incomplete is fine to display; wrong is not.
    """
    out: List[dict] = []
    for c in clusters:
        primary = c.primary
        verdict = evaluate(primary)
        if not verdict.discovery_usable:
            continue
        out.append({
            "source_ids": c.source_ids,
            "primary_source": primary.source.source_id,
            "record_id": _plain(unwrap(primary.source.record_id)),
            "nucleus": _plain(unwrap(primary.nucleus)),
            "evidence_class": primary.evidence_class.value,
            "spectrum_state": primary.spectrum_state.value,
            "identity_match_claimed_by_source": primary.identity_match.value,
            "identity_match_computed": (computed_by_record or {}).get(
                id(primary), primary.identity_match).value,
            "licence": _plain(unwrap(primary.source.licence)),
            "independent_support_count": c.independent_support_count(),
            "calibration_eligible": verdict.eligible,
            "rejected_by": verdict.rule_ids,
            "missing_metadata": primary.missing_metadata(),
        })
    return out


def build_nmr_sections(
    submitted: MoleculeIdentity,
    records: Iterable[NMRRecord],
    *,
    blocked_sources: Sequence[str] = (),
    rights_review_sources: Sequence[str] = (),
) -> List[Section]:
    """Build the measured-NMR sections of a dossier.

    ``blocked_sources`` and ``rights_review_sources`` are the sources we could not consult.
    They are reported explicitly so an empty result never reads as "no data exists".
    """
    records = list(records)
    sections: List[Section] = []

    exact, related, unrelated, unverifiable, disagreements = _split_by_identity(
        submitted, records)
    computed_by_record = {
        id(v.record): v.computed for v in classify_identity(submitted, records)
    }
    exact_clusters = cluster_records(exact)
    related_clusters = cluster_records(related)

    eligible = [c for c in exact_clusters if evaluate(c.primary).eligible]

    # -- measured NMR on the exact molecule -----------------------------------
    if eligible:
        sections.append(Section(
            name="measured_nmr_exact",
            status=FieldStatus.FOUND,
            detail=(f"{len(eligible)} calibration-eligible experiment(s) on the exact "
                    f"molecule, from {len(exact_clusters)} distinct experiment(s)."),
            evidence=_cluster_evidence(eligible, computed_by_record),
        ))
    elif exact_clusters:
        sections.append(Section(
            name="measured_nmr_exact",
            status=FieldStatus.FOUND,
            detail=("Spectra found on the exact molecule, but none passed the strict "
                    "calibration gate. Shown as discovery context only."),
            evidence=_cluster_evidence(exact_clusters, computed_by_record),
        ))
    elif blocked_sources:
        sections.append(Section(
            name="measured_nmr_exact",
            status=FieldStatus.ACCESS_BLOCKED,
            detail=("No measured NMR retrieved, but " + ", ".join(sorted(set(blocked_sources)))
                    + " could not be reached. This is not evidence that no data exists."),
        ))
    else:
        sections.append(Section(
            name="measured_nmr_exact",
            status=FieldStatus.NOT_FOUND,
            detail="No measured NMR found for this exact structure in the sources consulted.",
        ))

    # -- related structures, kept separate ------------------------------------
    if related_clusters:
        sections.append(Section(
            name="related_structure_nmr",
            status=FieldStatus.FOUND,
            detail=("Spectra for related structures (different salt, tautomer, isotope, "
                    "stereochemistry or connectivity-only match). These can inform a "
                    "comparison but are NOT measurements of the submitted molecule."),
            evidence=_cluster_evidence(related_clusters, computed_by_record),
        ))
    else:
        sections.append(Section(
            name="related_structure_nmr",
            status=FieldStatus.NOT_FOUND,
            detail="No related-structure spectra retrieved.",
        ))

    # -- records whose identity could not be established ----------------------
    if unverifiable:
        sections.append(Section(
            name="identity_unverifiable",
            status=FieldStatus.NOT_FOUND,
            detail=(f"{len(unverifiable)} record(s) could not be compared to the submitted "
                    "molecule because one side carries no InChIKey. They are excluded from "
                    "both the exact and the related sections: filing them as 'related' "
                    "would assert a relationship nobody established."),
            evidence=[{"source_id": r.source.source_id,
                       "record_id": _plain(unwrap(r.source.record_id))}
                      for r in unverifiable],
        ))

    # -- records that are simply a different compound -------------------------
    if unrelated:
        sections.append(Section(
            name="identity_unrelated",
            status=FieldStatus.NOT_FOUND,
            detail=(f"{len(unrelated)} retrieved record(s) are a different compound from the "
                    "submitted molecule and are not shown as evidence for it."),
            evidence=[{"source_id": r.source.source_id,
                       "record_id": _plain(unwrap(r.source.record_id))}
                      for r in unrelated],
        ))

    # -- claims the structures do not support ---------------------------------
    if disagreements:
        sections.append(Section(
            name="identity_claims_rejected",
            status=FieldStatus.NOT_FOUND,
            detail=(f"{len(disagreements)} record(s) asserted an identity relationship the "
                    "structures do not support. The computed comparison was used instead. "
                    "A source or mapping claiming 'exact' is a claim, not a verification."),
            evidence=[{"source_id": v.record.source.source_id,
                       "record_id": _plain(unwrap(v.record.source.record_id)),
                       "claimed": v.claimed.value,
                       "computed": v.computed.value}
                      for v in disagreements],
        ))

    # -- what we could not consult --------------------------------------------
    if blocked_sources:
        sections.append(Section(
            name="sources_access_blocked",
            status=FieldStatus.ACCESS_BLOCKED,
            detail="Could not be reached: " + ", ".join(sorted(set(blocked_sources))),
            evidence=[{"source_id": s} for s in sorted(set(blocked_sources))],
        ))
    if rights_review_sources:
        sections.append(Section(
            name="sources_rights_review_needed",
            status=FieldStatus.RIGHTS_REVIEW_NEEDED,
            detail=("Held back pending a rights check on the exact data: "
                    + ", ".join(sorted(set(rights_review_sources)))),
            evidence=[{"source_id": s} for s in sorted(set(rights_review_sources))],
        ))

    return sections


def build(
    submitted: MoleculeIdentity,
    records: Iterable[NMRRecord] = (),
    *,
    blocked_sources: Sequence[str] = (),
    rights_review_sources: Sequence[str] = (),
    unsupported_sections: Sequence[str] = (),
) -> MoleculeDossier:
    """Assemble a dossier. Sections NMRx cannot compute are marked UNSUPPORTED, not omitted."""
    dossier = MoleculeDossier(submitted=submitted)

    dossier.add(Section(
        name="exact_identity",
        status=FieldStatus.FOUND if unwrap(submitted.inchikey) else FieldStatus.NOT_FOUND,
        detail=("Exact structure pinned by InChIKey." if unwrap(submitted.inchikey)
                else "No InChIKey supplied; every downstream match is connectivity-only at best."),
        evidence=[{"inchikey": _plain(unwrap(submitted.inchikey)),
                   "smiles": _plain(unwrap(submitted.smiles)),
                   "formula": _plain(unwrap(submitted.formula))}],
    ))

    for section in build_nmr_sections(
        submitted, records,
        blocked_sources=blocked_sources,
        rights_review_sources=rights_review_sources,
    ):
        dossier.add(section)

    for name in unsupported_sections:
        dossier.add(Section(
            name=name,
            status=FieldStatus.UNSUPPORTED,
            detail=("Outside the current NMRx engine's validated domain. Searchability in a "
                    "database does not imply the calculation is supported."),
        ))

    return dossier
