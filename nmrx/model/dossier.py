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
from .provenance import FieldStatus, IdentityMatch, unwrap
from .records import MoleculeIdentity, NMRRecord


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
                "inchikey": unwrap(self.submitted.inchikey),
                "smiles": unwrap(self.submitted.smiles),
                "formula": unwrap(self.submitted.formula),
            },
            "sections": [s.to_dict() for s in self.sections],
            "status_summary": self.status_summary(),
        }


def _split_by_identity(records: Sequence[NMRRecord]) -> tuple:
    """Exact-molecule records and related-structure records, never mixed."""
    exact = [r for r in records if r.identity_match is IdentityMatch.EXACT]
    related = [r for r in records if r.identity_match is not IdentityMatch.EXACT]
    return exact, related


def _cluster_evidence(clusters: Sequence[ExperimentCluster]) -> List[dict]:
    out: List[dict] = []
    for c in clusters:
        primary = c.primary
        verdict = evaluate(primary)
        out.append({
            "source_ids": c.source_ids,
            "primary_source": primary.source.source_id,
            "record_id": unwrap(primary.source.record_id),
            "nucleus": unwrap(primary.nucleus),
            "evidence_class": primary.evidence_class.value,
            "spectrum_state": primary.spectrum_state.value,
            "identity_match": primary.identity_match.value,
            "licence": unwrap(primary.source.licence),
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

    exact, related = _split_by_identity(records)
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
            evidence=_cluster_evidence(eligible),
        ))
    elif exact_clusters:
        sections.append(Section(
            name="measured_nmr_exact",
            status=FieldStatus.FOUND,
            detail=("Spectra found on the exact molecule, but none passed the strict "
                    "calibration gate. Shown as discovery context only."),
            evidence=_cluster_evidence(exact_clusters),
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
            evidence=_cluster_evidence(related_clusters),
        ))
    else:
        sections.append(Section(
            name="related_structure_nmr",
            status=FieldStatus.NOT_FOUND,
            detail="No related-structure spectra retrieved.",
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
        evidence=[{"inchikey": unwrap(submitted.inchikey),
                   "smiles": unwrap(submitted.smiles),
                   "formula": unwrap(submitted.formula)}],
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
