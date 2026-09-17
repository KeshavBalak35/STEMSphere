"""Records must not invent conditions, and atom mappings must belong to their molecule."""

import unittest

from nmrx.model.provenance import UNKNOWN, Lineage, is_known
from nmrx.model.records import (
    ExperimentalConditions,
    MoleculeIdentity,
    NMRRecord,
    ShiftAssignment,
    SourceRef,
)

ASPIRIN_KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"


def _record(**kw):
    base = dict(
        molecule=MoleculeIdentity(inchikey=ASPIRIN_KEY, atom_count=13),
        source=SourceRef(source_id="nmrshiftdb2", record_id="1"),
        nucleus="13C",
    )
    base.update(kw)
    return NMRRecord(**base)


class TestConditionsDefaultToUnknown(unittest.TestCase):
    def test_a_fresh_conditions_object_knows_nothing(self):
        c = ExperimentalConditions()
        for f in ("solvent", "temperature_k", "reference_compound"):
            with self.subTest(f=f):
                self.assertIs(getattr(c, f), UNKNOWN)

    def test_missing_list_names_every_absent_required_field(self):
        c = ExperimentalConditions(solvent="CDCl3")
        self.assertEqual(c.missing_for_calibration(), ["temperature_k", "reference_compound"])
        self.assertFalse(c.is_calibration_complete())

    def test_complete_conditions_pass(self):
        c = ExperimentalConditions(solvent="CDCl3", temperature_k=298.0, reference_compound="TMS")
        self.assertEqual(c.missing_for_calibration(), [])
        self.assertTrue(c.is_calibration_complete())


class TestAtomMapping(unittest.TestCase):
    def test_index_beyond_the_molecule_is_a_problem(self):
        rec = _record(shifts=[ShiftAssignment(20, "C", 100.0)])
        self.assertTrue(any("outside" in p for p in rec.atom_index_problems()))

    def test_negative_index_is_a_problem(self):
        rec = _record(shifts=[ShiftAssignment(-1, "C", 100.0)])
        self.assertTrue(any("negative" in p for p in rec.atom_index_problems()))

    def test_one_atom_cannot_own_two_shifts(self):
        rec = _record(shifts=[ShiftAssignment(3, "C", 100.0), ShiftAssignment(3, "C", 120.0)])
        self.assertTrue(any("assigned to 2 shifts" in p for p in rec.atom_index_problems()))

    def test_unassigned_peaks_are_not_mapping_errors(self):
        rec = _record(shifts=[ShiftAssignment(None, "C", 100.0)])
        self.assertEqual(rec.atom_index_problems(), [])
        self.assertFalse(rec.has_any_assignment)

    def test_unknown_atom_count_does_not_fabricate_a_bound(self):
        rec = NMRRecord(
            molecule=MoleculeIdentity(inchikey=ASPIRIN_KEY),   # atom_count UNKNOWN
            source=SourceRef(source_id="x"),
            shifts=[ShiftAssignment(999, "C", 1.0)],
        )
        self.assertEqual(rec.atom_index_problems(), [])


class TestIdentityComparison(unittest.TestCase):
    def test_same_key_is_exact(self):
        a = MoleculeIdentity(inchikey=ASPIRIN_KEY)
        self.assertTrue(a.compare(MoleculeIdentity(inchikey=ASPIRIN_KEY)).is_exact)

    def test_same_skeleton_different_suffix_is_not_exact(self):
        """Stereo/isotope/protonation layers differ -- we must not call that the same molecule."""
        a = MoleculeIdentity(inchikey=ASPIRIN_KEY)
        b = MoleculeIdentity(inchikey="BSYNRYMUTXBXSQ-XXXXXXXXXX-N")
        self.assertFalse(a.compare(b).is_exact)

    def test_unknown_key_never_yields_an_exact_match(self):
        a = MoleculeIdentity(inchikey=ASPIRIN_KEY)
        self.assertFalse(a.compare(MoleculeIdentity()).is_exact)


class TestLineageIntegrity(unittest.TestCase):
    def test_a_mirror_must_name_what_it_mirrors(self):
        with self.assertRaises(ValueError):
            SourceRef(source_id="mona", lineage=Lineage.MIRRORED_COPY)

    def test_a_mirror_with_an_origin_is_accepted(self):
        ref = SourceRef(source_id="mona", lineage=Lineage.MIRRORED_COPY, original_source_id="massbank")
        self.assertEqual(ref.original_source_id, "massbank")


class TestMissingMetadata(unittest.TestCase):
    def test_bare_record_reports_everything_it_lacks(self):
        rec = _record()
        missing = rec.missing_metadata()
        for expected in ("solvent", "temperature_k", "reference_compound",
                         "source.licence", "atom_assignments"):
            with self.subTest(expected=expected):
                self.assertIn(expected, missing)

    def test_serialised_record_shows_unknown_as_null_not_a_default(self):
        d = _record().to_dict()
        self.assertIsNone(d["conditions"]["solvent"])
        self.assertIn("missing_metadata", d)


if __name__ == "__main__":
    unittest.main()
