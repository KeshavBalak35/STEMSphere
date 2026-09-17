"""The strict gate. A record enters calibration only when every rule passes."""

import unittest

from nmrx.model.calibration import CALIBRATION_RULES, evaluate, rule_catalogue
from nmrx.model.provenance import (
    EvidenceClass,
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


def good_record(**overrides) -> NMRRecord:
    """A record that passes every rule. Tests break exactly one thing at a time."""
    base = dict(
        molecule=MoleculeIdentity(inchikey=KEY, atom_count=4),
        source=SourceRef(source_id="nmrshiftdb2", record_id="42", licence="CC BY-SA 3.0"),
        nucleus="13C",
        evidence_class=EvidenceClass.MEASURED,
        spectrum_state=SpectrumState.ASSIGNED_PEAKS,
        identity_match=IdentityMatch.EXACT,
        conditions=ExperimentalConditions(solvent="CDCl3", temperature_k=298.0,
                                          reference_compound="TMS"),
        shifts=[ShiftAssignment(i, "C", 100.0 + i) for i in range(4)],
    )
    base.update(overrides)
    return NMRRecord(**base)


class TestHappyPath(unittest.TestCase):
    def test_a_complete_measured_assigned_record_passes(self):
        verdict = evaluate(good_record())
        self.assertTrue(verdict.eligible, verdict.rule_ids)
        self.assertEqual(verdict.rejections, [])


class TestEachRuleRejects(unittest.TestCase):
    def assert_rejected_by(self, rule_id, record):
        verdict = evaluate(record)
        self.assertFalse(verdict.eligible)
        self.assertIn(rule_id, verdict.rule_ids)

    def test_cal001_calculated_values_are_excluded(self):
        for ec in (EvidenceClass.QUANTUM_CALCULATED, EvidenceClass.MODEL_PREDICTED,
                   EvidenceClass.LITERATURE_EXTRACTED):
            with self.subTest(ec=ec):
                self.assert_rejected_by("CAL-001", good_record(evidence_class=ec))

    def test_cal002_a_related_compound_is_not_the_submitted_molecule(self):
        for im in (IdentityMatch.DIFFERENT_SALT, IdentityMatch.DIFFERENT_TAUTOMER,
                   IdentityMatch.DIFFERENT_STEREOISOMER, IdentityMatch.CONNECTIVITY_ONLY):
            with self.subTest(im=im):
                self.assert_rejected_by("CAL-002", good_record(identity_match=im))

    def test_cal003_a_mirrored_copy_is_not_the_experiment(self):
        mirror = SourceRef(source_id="mona", record_id="m", licence="CC BY 4.0",
                           lineage=Lineage.MIRRORED_COPY, original_source_id="massbank")
        self.assert_rejected_by("CAL-003", good_record(source=mirror))

    def test_cal004_unknown_nucleus_is_rejected(self):
        self.assert_rejected_by("CAL-004", good_record(nucleus=None))

    def test_cal004_unsupported_nucleus_is_rejected(self):
        self.assert_rejected_by("CAL-004", good_record(nucleus="235U"))

    def test_cal005_each_missing_condition_rejects(self):
        for field in ("solvent", "temperature_k", "reference_compound"):
            kw = dict(solvent="CDCl3", temperature_k=298.0, reference_compound="TMS")
            kw.pop(field)
            with self.subTest(missing=field):
                rec = good_record(conditions=ExperimentalConditions(**kw))
                self.assert_rejected_by("CAL-005", rec)
                detail = [r.detail for r in evaluate(rec).rejections if r.rule_id == "CAL-005"][0]
                self.assertIn(field, detail)
                self.assertIn("must not be invented", detail)

    def test_cal006_partial_assignment_is_rejected(self):
        shifts = [ShiftAssignment(0, "C", 100.0), ShiftAssignment(None, "C", 110.0)]
        self.assert_rejected_by("CAL-006", good_record(shifts=shifts))

    def test_cal006_image_only_spectrum_is_rejected(self):
        self.assert_rejected_by("CAL-006", good_record(spectrum_state=SpectrumState.IMAGE_ONLY))

    def test_cal006_no_shifts_is_rejected(self):
        self.assert_rejected_by("CAL-006", good_record(shifts=[]))

    def test_cal007_out_of_range_atom_index_is_rejected(self):
        shifts = [ShiftAssignment(0, "C", 1.0), ShiftAssignment(99, "C", 2.0),
                  ShiftAssignment(2, "C", 3.0), ShiftAssignment(3, "C", 4.0)]
        self.assert_rejected_by("CAL-007", good_record(shifts=shifts))

    def test_cal008_unknown_licence_is_rejected(self):
        ref = SourceRef(source_id="nmrshiftdb2", record_id="42")   # licence UNKNOWN
        self.assert_rejected_by("CAL-008", good_record(source=ref))

    def test_cal009_missing_inchikey_is_rejected(self):
        self.assert_rejected_by("CAL-009", good_record(molecule=MoleculeIdentity(atom_count=4)))


class TestDiscoveryVersusCalibration(unittest.TestCase):
    def test_an_incomplete_record_is_still_discovery_usable(self):
        """The map: keep incomplete records for discovery, out of strict calibration."""
        rec = good_record(conditions=ExperimentalConditions(solvent="CDCl3"))
        verdict = evaluate(rec)
        self.assertFalse(verdict.eligible)
        self.assertTrue(verdict.discovery_usable)

    def test_an_invalid_atom_mapping_is_not_even_discovery_usable(self):
        """Incomplete is fine to show. Wrong is not."""
        shifts = [ShiftAssignment(0, "C", 1.0), ShiftAssignment(0, "C", 2.0)]
        verdict = evaluate(good_record(shifts=shifts))
        self.assertFalse(verdict.discovery_usable)
        self.assertEqual(verdict.discovery_block.rule_id, "CAL-007")


class TestGateReporting(unittest.TestCase):
    def test_all_failures_are_collected_not_just_the_first(self):
        rec = NMRRecord(molecule=MoleculeIdentity(), source=SourceRef(source_id="x"))
        verdict = evaluate(rec)
        self.assertGreaterEqual(len(verdict.rejections), 4)

    def test_catalogue_covers_every_implemented_rule(self):
        catalogue_ids = {r["rule_id"] for r in rule_catalogue()}
        self.assertEqual(len(catalogue_ids), len(CALIBRATION_RULES))

    def test_verdict_serialises(self):
        d = evaluate(good_record(nucleus=None)).to_dict()
        self.assertIn("rejections", d)
        self.assertEqual(d["rejections"][0]["rule_id"], "CAL-004")


if __name__ == "__main__":
    unittest.main()
