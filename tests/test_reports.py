"""Reports must not overstate what we have."""

import unittest

from nmrx.model.provenance import EvidenceClass, IdentityMatch, Lineage, SpectrumState
from nmrx.model.records import (
    ExperimentalConditions,
    MoleculeIdentity,
    NMRRecord,
    ShiftAssignment,
    SourceRef,
)
from nmrx.reports.blockers import build as build_blockers
from nmrx.reports.blockers import from_probe
from nmrx.reports.coverage import capability_matrix, record_missingness, source_coverage
from nmrx.sources.registry import load_registry

KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"


def _complete():
    return NMRRecord(
        molecule=MoleculeIdentity(inchikey=KEY, atom_count=2),
        source=SourceRef(source_id="nmrshiftdb2", record_id="1", licence="CC BY-SA 3.0"),
        nucleus="13C",
        evidence_class=EvidenceClass.MEASURED,
        spectrum_state=SpectrumState.ASSIGNED_PEAKS,
        identity_match=IdentityMatch.EXACT,
        conditions=ExperimentalConditions(solvent="CDCl3", temperature_k=298.0,
                                          reference_compound="TMS"),
        shifts=[ShiftAssignment(0, "C", 10.0), ShiftAssignment(1, "C", 20.0)],
    )


def _bare():
    return NMRRecord(molecule=MoleculeIdentity(), source=SourceRef(source_id="nmrxiv"))


class TestSourceCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coverage = source_coverage(load_registry())

    def test_counts_cover_the_whole_registry(self):
        self.assertEqual(self.coverage["registry_size"], 50)
        self.assertEqual(sum(self.coverage["by_tier"].values()), 50)
        self.assertEqual(sum(self.coverage["by_status"].values()), 50)

    def test_measured_nmr_with_assignments_is_a_small_set(self):
        """The headline number: very few sources clear both bars."""
        ids = self.coverage["nmr"]["measured_with_assignments_and_conditions"]["ids"]
        self.assertIn("nmrshiftdb2", ids)
        self.assertLessEqual(len(ids), 6, "if this grows, check nobody upgraded a verdict")

    def test_prohibited_sources_are_reported(self):
        self.assertIn("sdbs", self.coverage["prohibited"]["ids"])

    def test_harvestable_never_includes_prohibited(self):
        self.assertNotIn("sdbs", self.coverage["harvestable_now_if_network_opened"]["ids"])


class TestCapabilityMatrix(unittest.TestCase):
    def test_unassessed_sources_are_shown_not_dropped(self):
        rows = capability_matrix(load_registry(), {})
        self.assertEqual(len(rows), 50)
        self.assertTrue(all(r["assessed"] is False for r in rows))
        self.assertEqual(rows[0]["capabilities"]["find_structure"]["verdict"], "unassessed")

    def test_supplied_assessments_are_joined_in(self):
        caps = {"nmrshiftdb2": {"find_structure": {"verdict": "yes", "evidence": "x"}}}
        rows = {r["source_id"]: r for r in capability_matrix(load_registry(), caps)}
        self.assertTrue(rows["nmrshiftdb2"]["assessed"])
        self.assertEqual(rows["nmrshiftdb2"]["capabilities"]["find_structure"]["verdict"], "yes")


class TestRecordMissingness(unittest.TestCase):
    def test_eligible_and_incomplete_records_are_counted_separately(self):
        report = record_missingness([_complete(), _bare()])
        self.assertEqual(report["record_count"], 2)
        self.assertEqual(report["calibration_eligible"], 1)
        self.assertEqual(report["discovery_only"], 1)

    def test_missing_fields_are_tallied(self):
        report = record_missingness([_bare()])
        fields = {row["field"] for row in report["missing_fields"]}
        for expected in ("solvent", "temperature_k", "reference_compound", "atom_assignments"):
            with self.subTest(expected=expected):
                self.assertIn(expected, fields)

    def test_missingness_starts_unattributed(self):
        """We must not guess whether a gap is upstream or our own parser."""
        report = record_missingness([_bare()])
        self.assertTrue(all(row["attribution"] == "unattributed"
                            for row in report["missing_fields"]))

    def test_rejections_are_grouped_by_rule(self):
        report = record_missingness([_bare()])
        rules = {row["rule_id"] for row in report["rejections_by_rule"]}
        self.assertIn("CAL-005", rules)
        self.assertIn("CAL-009", rules)

    def test_per_source_breakdown_is_kept(self):
        report = record_missingness([_bare()])
        self.assertIn("nmrxiv", report["missing_fields_by_source"])

    def test_an_empty_run_does_not_crash(self):
        report = record_missingness([])
        self.assertEqual(report["record_count"], 0)
        self.assertEqual(report["missing_fields"], [])


class TestBlockerReport(unittest.TestCase):
    def test_one_blocker_per_blocked_host_not_per_url(self):
        probe = {"results": [
            {"host": "a.example", "source_id": "s1", "url": "https://a.example/1",
             "purpose": "p", "classification": "blocked_by_environment_network_policy",
             "error": "403"},
            {"host": "a.example", "source_id": "s1", "url": "https://a.example/2",
             "purpose": "p", "classification": "blocked_by_environment_network_policy",
             "error": "403"},
            {"host": "b.example", "source_id": "s2", "url": "https://b.example/1",
             "purpose": "p", "classification": "blocked_by_environment_network_policy",
             "error": "403"},
        ]}
        blockers = from_probe(probe)
        self.assertEqual({b.host for b in blockers}, {"a.example", "b.example"})

    def test_a_reachable_host_produces_no_blocker(self):
        probe = {"results": [{"host": "a.example", "source_id": "s", "url": "u",
                              "purpose": "p", "classification": "reachable"}]}
        self.assertEqual(from_probe(probe), [])

    def test_network_blockers_name_the_environment_setting(self):
        report = build_blockers()
        self.assertTrue(report["network_blockers"])
        for b in report["network_blockers"]:
            with self.subTest(host=b["host"]):
                self.assertIn("Allowed domains", b["action"])
                self.assertEqual(b["layer"], "environment_network")

    def test_prohibited_sources_are_never_described_as_merely_ungranted(self):
        report = build_blockers()
        sdbs = [b for b in report["rights_and_policy_blockers"] if b["source_id"] == "sdbs"]
        self.assertTrue(sdbs)
        self.assertEqual(sdbs[0]["layer"], "provider_prohibition")
        self.assertIn("cannot be resolved", sdbs[0]["resolved_by"])


if __name__ == "__main__":
    unittest.main()
