"""Unknown must stay unknown, and recovered values must carry their derivation."""

import unittest

from nmrx.model.provenance import (
    UNKNOWN,
    EvidenceClass,
    IdentityMatch,
    Lineage,
    Provenanced,
    SpectrumState,
    ValueOrigin,
    is_known,
    unwrap,
)


class TestUnknownSentinel(unittest.TestCase):
    def test_unknown_is_a_singleton(self):
        from nmrx.model.provenance import _Unknown
        self.assertIs(_Unknown(), UNKNOWN)

    def test_unknown_is_falsy_but_not_none(self):
        self.assertFalse(UNKNOWN)
        self.assertIsNot(UNKNOWN, None)

    def test_unknown_equals_only_itself(self):
        for other in (None, "", 0, False, "unknown", []):
            with self.subTest(other=other):
                self.assertNotEqual(UNKNOWN, other)

    def test_is_known_rejects_unknown_and_none(self):
        self.assertFalse(is_known(UNKNOWN))
        self.assertFalse(is_known(None))
        self.assertTrue(is_known(0))        # a real zero is a value
        self.assertTrue(is_known("CDCl3"))

    def test_unknown_survives_a_round_trip(self):
        import pickle
        self.assertIs(pickle.loads(pickle.dumps(UNKNOWN)), UNKNOWN)


class TestProvenancedValues(unittest.TestCase):
    def test_recovered_value_requires_a_citation(self):
        """Recovery without evidence is indistinguishable from invention."""
        for origin in (ValueOrigin.RECOVERED_FROM_PUBLICATION, ValueOrigin.DATABASE_CONVENTION):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                Provenanced(value="CDCl3", origin=origin)

    def test_source_supplied_value_needs_no_citation(self):
        p = Provenanced(value="CDCl3", origin=ValueOrigin.SOURCE_RECORD)
        self.assertTrue(p.is_from_source)
        self.assertFalse(p.is_recovered)

    def test_recovered_value_stays_distinguishable_from_source_value(self):
        recovered = Provenanced(value=298.0, origin=ValueOrigin.RECOVERED_FROM_PUBLICATION,
                                evidence="doi:10.1000/example")
        from_source = Provenanced(value=298.0, origin=ValueOrigin.SOURCE_RECORD)
        self.assertEqual(unwrap(recovered), unwrap(from_source))
        self.assertNotEqual(recovered.origin, from_source.origin)
        self.assertTrue(recovered.is_recovered)

    def test_unwrap_passes_plain_values_through(self):
        self.assertEqual(unwrap("x"), "x")
        self.assertIs(unwrap(UNKNOWN), UNKNOWN)


class TestAxesDoNotCollapse(unittest.TestCase):
    def test_only_measured_is_experimental(self):
        self.assertTrue(EvidenceClass.MEASURED.is_experimental)
        for other in (EvidenceClass.QUANTUM_CALCULATED, EvidenceClass.MODEL_PREDICTED,
                      EvidenceClass.LITERATURE_EXTRACTED):
            with self.subTest(other=other):
                self.assertFalse(other.is_experimental)

    def test_only_assigned_peaks_carry_atom_assignments(self):
        self.assertTrue(SpectrumState.ASSIGNED_PEAKS.has_atom_assignments)
        for other in (SpectrumState.RAW, SpectrumState.PROCESSED,
                      SpectrumState.UNASSIGNED_PEAKS, SpectrumState.IMAGE_ONLY):
            with self.subTest(other=other):
                self.assertFalse(other.has_atom_assignments)

    def test_image_only_has_no_numeric_values(self):
        self.assertFalse(SpectrumState.IMAGE_ONLY.has_numeric_values)

    def test_only_the_original_experiment_is_independent_evidence(self):
        self.assertTrue(Lineage.ORIGINAL_EXPERIMENT.is_independent_evidence)
        self.assertFalse(Lineage.MIRRORED_COPY.is_independent_evidence)
        self.assertFalse(Lineage.REPROCESSED_VERSION.is_independent_evidence)

    def test_only_exact_identity_is_exact(self):
        self.assertTrue(IdentityMatch.EXACT.is_exact)
        for other in IdentityMatch:
            if other is not IdentityMatch.EXACT:
                with self.subTest(other=other):
                    self.assertFalse(other.is_exact)


if __name__ == "__main__":
    unittest.main()
