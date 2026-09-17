"""End to end: payload -> adapter -> records -> dedup -> calibration gate -> dossier.

All payloads are synthetic. The point of this test is that the *pipeline* holds together
and that a sparse record degrades gracefully instead of being quietly completed.
"""

import unittest

from nmrx.adapters import SourceAdapter
from nmrx.model import MoleculeIdentity, cluster_records, evaluate
from nmrx.model.dossier import build
from nmrx.model.provenance import FieldStatus, IdentityMatch, Lineage
from nmrx.reports.coverage import record_missingness

KEY = "AAAAAAAAAAAAAA-BBBBBBBBBB-N"

COMPLETE = {
    "id": "SYN-A", "inchikey": KEY, "nucleus": "13C", "solvent": "CDCl3",
    "temperature_k": 298.0, "reference": "TMS", "atom_count": 2, "license": "CC BY 4.0",
    "peaks": [{"atom": 0, "element": "C", "ppm": 10.0}, {"atom": 1, "element": "C", "ppm": 20.0}],
}
SPARSE = {
    "id": "SYN-B", "inchikey": KEY, "nucleus": "1H", "atom_count": 2,
    "peaks": [{"element": "H", "ppm": 7.26}],
}


def _parse(*payloads):
    adapter = SourceAdapter.load("nmrshiftdb2")
    records = []
    for p in payloads:
        records.extend(adapter.parse(p))
    for r in records:
        r.identity_match = IdentityMatch.EXACT
    return records


class TestPipeline(unittest.TestCase):
    def test_a_complete_record_survives_the_whole_pipeline(self):
        records = _parse(COMPLETE)
        self.assertEqual(len(records), 1)
        self.assertTrue(evaluate(records[0]).eligible)

    def test_a_sparse_record_is_rejected_for_the_right_reasons(self):
        records = _parse(SPARSE)
        verdict = evaluate(records[0])
        self.assertFalse(verdict.eligible)
        self.assertIn("CAL-005", verdict.rule_ids)   # conditions missing
        self.assertIn("CAL-006", verdict.rule_ids)   # unassigned peak
        self.assertIn("CAL-008", verdict.rule_ids)   # licence unknown
        self.assertTrue(verdict.discovery_usable)

    def test_a_sparse_record_is_never_silently_completed(self):
        from nmrx.model.provenance import UNKNOWN
        record = _parse(SPARSE)[0]
        for field in ("solvent", "temperature_k", "reference_compound"):
            with self.subTest(field=field):
                self.assertIs(getattr(record.conditions, field), UNKNOWN)

    def test_mixed_records_are_counted_separately(self):
        report = record_missingness(_parse(COMPLETE, SPARSE))
        self.assertEqual(report["record_count"], 2)
        self.assertEqual(report["calibration_eligible"], 1)
        self.assertEqual(report["discovery_only"], 1)

    def test_the_dossier_reports_both_findings_and_blocked_sources(self):
        dossier = build(
            MoleculeIdentity(inchikey=KEY, atom_count=2),
            _parse(COMPLETE, SPARSE),
            blocked_sources=["bmrb", "nmrxiv", "chemotion"],
        )
        self.assertIs(dossier.section("measured_nmr_exact").status, FieldStatus.FOUND)
        self.assertIs(dossier.section("sources_access_blocked").status, FieldStatus.ACCESS_BLOCKED)

    def test_two_different_nuclei_are_two_experiments(self):
        clusters = cluster_records(_parse(COMPLETE, SPARSE))
        self.assertEqual(len(clusters), 2)

    def test_the_same_spectrum_from_a_mirror_stays_one_experiment(self):
        from nmrx.model.records import SourceRef
        records = _parse(COMPLETE, COMPLETE)
        records[1].source = SourceRef(
            source_id="mona", record_id="m1", licence="CC BY 4.0",
            lineage=Lineage.MIRRORED_COPY, original_source_id="nmrshiftdb2",
        )
        clusters = cluster_records(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].independent_support_count(), 1)
        self.assertEqual(sorted(clusters[0].source_ids), ["mona", "nmrshiftdb2"])


class TestNothingReachesTheNetwork(unittest.TestCase):
    """The whole suite must be runnable offline."""

    def test_parsing_needs_no_client(self):
        adapter = SourceAdapter.load("nmrshiftdb2")
        self.assertIsNone(adapter.client)
        self.assertEqual(len(adapter.parse(COMPLETE)), 1)


if __name__ == "__main__":
    unittest.main()
