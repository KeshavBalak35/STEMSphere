"""A dossier must never let 'blocked' look like 'does not exist'."""

import unittest

from nmrx.model.dossier import build
from nmrx.model.provenance import (
    EvidenceClass,
    FieldStatus,
    IdentityMatch,
    Lineage,
    SpectrumState,
)
from nmrx.model.records import (
    ExperimentalConditions,
    MoleculeIdentity,
    NMRRecord,
    ShiftAssignment,
    SourceRef,
)

KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
#: Same connectivity skeleton, different second layer -- a genuinely related structure.
RELATED_KEY = "BSYNRYMUTXBXSQ-ZZZZZZZZZZ-N"
SUBMITTED = MoleculeIdentity(inchikey=KEY, smiles="CC", atom_count=2)


def record(identity_match=IdentityMatch.EXACT, complete=True, source_id="nmrshiftdb2",
           molecule_key=KEY):
    """Build a record.

    ``molecule_key`` is what actually decides exact-vs-related now, because the dossier
    computes the relationship from the structures. ``identity_match`` is only the record's
    *claim*, which the dossier tests rather than trusts.
    """
    conditions = (ExperimentalConditions(solvent="CDCl3", temperature_k=298.0,
                                         reference_compound="TMS")
                  if complete else ExperimentalConditions())
    return NMRRecord(
        molecule=MoleculeIdentity(inchikey=molecule_key, atom_count=2),
        source=SourceRef(source_id=source_id, record_id="r1",
                         licence="CC BY 4.0" if complete else None,
                         lineage=Lineage.ORIGINAL_EXPERIMENT),
        nucleus="13C",
        evidence_class=EvidenceClass.MEASURED,
        spectrum_state=SpectrumState.ASSIGNED_PEAKS,
        identity_match=identity_match,
        conditions=conditions,
        shifts=[ShiftAssignment(0, "C", 10.0), ShiftAssignment(1, "C", 20.0)],
    )


class TestStatusIsAlwaysExplicit(unittest.TestCase):
    def test_every_section_carries_a_status(self):
        dossier = build(SUBMITTED, [record()])
        self.assertTrue(dossier.sections)
        for section in dossier.sections:
            with self.subTest(section=section.name):
                self.assertIsInstance(section.status, FieldStatus)

    def test_blocked_is_not_reported_as_not_found(self):
        """The distinction the whole dossier exists to preserve."""
        dossier = build(SUBMITTED, [], blocked_sources=["nmrshiftdb2", "bmrb"])
        section = dossier.section("measured_nmr_exact")
        self.assertIs(section.status, FieldStatus.ACCESS_BLOCKED)
        self.assertIn("not evidence that no data exists", section.detail)

    def test_genuinely_empty_is_reported_as_not_found(self):
        dossier = build(SUBMITTED, [])
        self.assertIs(dossier.section("measured_nmr_exact").status, FieldStatus.NOT_FOUND)

    def test_unsupported_sections_are_shown_not_omitted(self):
        dossier = build(SUBMITTED, [], unsupported_sections=["inorganic_shieldings"])
        section = dossier.section("inorganic_shieldings")
        self.assertIs(section.status, FieldStatus.UNSUPPORTED)
        self.assertIn("Searchability in a database does not imply", section.detail)

    def test_rights_review_is_its_own_status(self):
        dossier = build(SUBMITTED, [], rights_review_sources=["rruff"])
        self.assertIs(dossier.section("sources_rights_review_needed").status,
                      FieldStatus.RIGHTS_REVIEW_NEEDED)


class TestRelatedStructuresStaySeparate(unittest.TestCase):
    def test_a_related_compound_never_enters_the_exact_section(self):
        dossier = build(SUBMITTED, [record(identity_match=IdentityMatch.DIFFERENT_SALT,
                                           molecule_key=RELATED_KEY)])
        self.assertIs(dossier.section("measured_nmr_exact").status, FieldStatus.NOT_FOUND)
        self.assertIs(dossier.section("related_structure_nmr").status, FieldStatus.FOUND)

    def test_a_record_claiming_exact_is_still_checked_against_the_structures(self):
        """A source (or a mapping bug) asserting "exact" is a claim, not a verification."""
        dossier = build(SUBMITTED, [record(identity_match=IdentityMatch.EXACT,
                                           molecule_key=RELATED_KEY)])
        self.assertIs(dossier.section("measured_nmr_exact").status, FieldStatus.NOT_FOUND)
        rejected = dossier.section("identity_claims_rejected")
        self.assertIsNotNone(rejected)
        self.assertEqual(rejected.evidence[0]["claimed"], "exact")
        self.assertEqual(rejected.evidence[0]["computed"], "connectivity_only")

    def test_a_different_compound_is_not_shown_as_related_either(self):
        dossier = build(SUBMITTED, [record(identity_match=IdentityMatch.EXACT,
                                           molecule_key="QQQQQQQQQQQQQQ-BBBBBBBBBB-N")])
        self.assertIs(dossier.section("measured_nmr_exact").status, FieldStatus.NOT_FOUND)
        self.assertIs(dossier.section("related_structure_nmr").status, FieldStatus.NOT_FOUND)
        self.assertIsNotNone(dossier.section("identity_unrelated"))

    def test_an_unpinned_record_is_neither_exact_nor_related(self):
        """Filing it as related would assert a relationship nobody established."""
        dossier = build(SUBMITTED, [record(molecule_key=None)])
        self.assertIs(dossier.section("measured_nmr_exact").status, FieldStatus.NOT_FOUND)
        self.assertIs(dossier.section("related_structure_nmr").status, FieldStatus.NOT_FOUND)
        self.assertIsNotNone(dossier.section("identity_unverifiable"))

    def test_related_section_says_it_is_not_a_measurement_of_the_molecule(self):
        dossier = build(SUBMITTED, [record(identity_match=IdentityMatch.CONNECTIVITY_ONLY,
                                           molecule_key=RELATED_KEY)])
        detail = dossier.section("related_structure_nmr").detail
        self.assertIn("NOT measurements of the submitted molecule", detail)

    def test_exact_and_related_do_not_share_evidence(self):
        dossier = build(SUBMITTED, [record(),
                                    record(identity_match=IdentityMatch.DIFFERENT_TAUTOMER,
                                           molecule_key=RELATED_KEY)])
        exact = dossier.section("measured_nmr_exact").evidence
        related = dossier.section("related_structure_nmr").evidence
        self.assertEqual(len(exact), 1)
        self.assertEqual(len(related), 1)
        self.assertEqual(exact[0]["identity_match_computed"], "exact")


class TestCalibrationVisibility(unittest.TestCase):
    def test_an_eligible_record_is_reported_as_eligible(self):
        dossier = build(SUBMITTED, [record()])
        evidence = dossier.section("measured_nmr_exact").evidence[0]
        self.assertTrue(evidence["calibration_eligible"])
        self.assertEqual(evidence["rejected_by"], [])

    def test_an_incomplete_record_is_shown_but_flagged(self):
        dossier = build(SUBMITTED, [record(complete=False)])
        section = dossier.section("measured_nmr_exact")
        self.assertIs(section.status, FieldStatus.FOUND)
        self.assertIn("none passed the strict calibration gate", section.detail)
        self.assertFalse(section.evidence[0]["calibration_eligible"])
        self.assertIn("CAL-005", section.evidence[0]["rejected_by"])

    def test_evidence_lists_what_is_missing(self):
        dossier = build(SUBMITTED, [record(complete=False)])
        missing = dossier.section("measured_nmr_exact").evidence[0]["missing_metadata"]
        self.assertIn("solvent", missing)

    def test_mirrored_copies_do_not_inflate_support(self):
        original = record()
        mirror = record(source_id="mona")
        mirror.source = SourceRef(source_id="mona", record_id="m", licence="CC BY 4.0",
                                  lineage=Lineage.MIRRORED_COPY,
                                  original_source_id="nmrshiftdb2")
        dossier = build(SUBMITTED, [original, mirror])
        evidence = dossier.section("measured_nmr_exact").evidence[0]
        self.assertEqual(evidence["independent_support_count"], 1)
        self.assertEqual(sorted(evidence["source_ids"]), ["mona", "nmrshiftdb2"])


class TestIdentity(unittest.TestCase):
    def test_a_molecule_without_an_inchikey_is_flagged(self):
        dossier = build(MoleculeIdentity(smiles="CC"), [])
        section = dossier.section("exact_identity")
        self.assertIs(section.status, FieldStatus.NOT_FOUND)
        self.assertIn("connectivity-only at best", section.detail)

    def test_dossier_serialises(self):
        d = build(SUBMITTED, [record()]).to_dict()
        self.assertIn("status_summary", d)
        self.assertEqual(d["submitted_molecule"]["inchikey"], KEY)


if __name__ == "__main__":
    unittest.main()
