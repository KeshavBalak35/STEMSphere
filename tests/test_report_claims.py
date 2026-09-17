"""REPORT.md states specific numbers. These tests keep it from drifting out of date.

A status report that quietly goes stale is worse than no report, because people keep quoting
it. Every headline figure in nmrx/REPORT.md is re-derived here from the actual data files.
"""

import json
import re
import unittest
from pathlib import Path

from nmrx.adapters import available_plans
from nmrx.adapters.base import AdapterPlan
from nmrx.reports.coverage import source_coverage
from nmrx.sources.registry import load_registry

ROOT = Path(__file__).resolve().parent.parent
REPORT = (ROOT / "nmrx" / "REPORT.md").read_text()
REVIEW = json.loads((ROOT / "nmrx" / "data" / "rights_review.json").read_text())
PROBE = json.loads((ROOT / "nmrx" / "data" / "probes" / "pilot_probe_2026-09-17.json").read_text())


class TestPilotFigures(unittest.TestCase):
    def test_the_report_states_the_real_request_and_byte_counts(self):
        self.assertEqual(PROBE["steps_executed"], 6)
        self.assertEqual(PROBE["total_bytes_downloaded"], 0)
        self.assertIn("6 requests, 0 bytes downloaded", REPORT)

    def test_every_pilot_host_named_in_the_report_was_actually_blocked(self):
        blocked = set(PROBE["blocked_hosts"])
        self.assertEqual(len(blocked), 6)
        for host in blocked:
            with self.subTest(host=host):
                self.assertIn(host, REPORT)

    def test_the_report_does_not_claim_any_data_was_retrieved(self):
        self.assertIn("0 records retrieved", REPORT)


class TestRegistryFigures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()
        cls.coverage = source_coverage(cls.registry)

    def test_fifty_sources(self):
        self.assertEqual(len(self.registry), 50)

    def test_every_source_is_documented_only_as_stated(self):
        self.assertEqual(len(self.registry.by_status("documented_only")), 50)
        self.assertIn("Status of every one of the 50: `documented_only`", REPORT)

    def test_exactly_four_sources_clear_both_nmr_bars(self):
        ids = self.coverage["nmr"]["measured_with_assignments_and_conditions"]["ids"]
        self.assertEqual(sorted(ids), sorted(["nmrshiftdb2", "bmrb", "nmrxiv", "chemotion"]))
        self.assertIn("exactly **4**", REPORT)

    def test_the_stated_nmr_counts_are_real(self):
        self.assertEqual(len(self.registry.nmr_sources()), 10)
        self.assertEqual(len(self.registry.measured_nmr_sources()), 8)
        self.assertIn("10 carry NMR", REPORT)
        self.assertIn("8 of those claim measured evidence", REPORT)


class TestRightsFigures(unittest.TestCase):
    def test_the_bucket_counts_in_the_report_match_the_review(self):
        expected = {
            "usable_when_unblocked": 19,
            "rights_unverified": 20,
            "non_commercial_only": 3,
            "licence_or_account_required": 7,
            "harvesting_prohibited": 1,
        }
        for bucket, count in expected.items():
            with self.subTest(bucket=bucket):
                self.assertEqual(len(REVIEW["buckets"][bucket]), count)
        self.assertEqual(sum(expected.values()), 50)

    def test_the_headline_claim_about_unsettled_rights_holds(self):
        unverified = set(REVIEW["buckets"]["rights_unverified"])
        for source_id in ("nmrshiftdb2", "bmrb", "nmrxiv", "chemotion"):
            with self.subTest(source=source_id):
                self.assertIn(source_id, unverified)
        self.assertIn("20 of 50", REPORT)


class TestAdapterFigures(unittest.TestCase):
    def test_five_sources_have_plans_and_none_is_live_capable(self):
        plans = available_plans()
        self.assertEqual(len(plans), 5)
        for source_id in plans:
            with self.subTest(source=source_id):
                self.assertFalse(AdapterPlan.load(source_id).schema_confirmed)
        self.assertIn("none claims to", REPORT)


class TestReportHonesty(unittest.TestCase):
    def test_the_report_states_there_was_no_prior_nmrx_code(self):
        self.assertIn("no existing NMRx code in this repository", REPORT)

    def test_the_report_flags_the_caps_as_proposed_not_inherited(self):
        self.assertIn("proposed, not inherited", REPORT)

    def test_the_stated_test_count_matches_reality(self):
        """The report quotes a test count. Count the suite and check it.

        Counted by loading the suite in-process, NOT by shelling out to another
        ``unittest discover`` -- that would re-enter this very test and recurse forever.
        """
        claimed = re.search(r"(\d+) offline tests pass", REPORT)
        self.assertIsNotNone(claimed, "REPORT.md no longer states a test count")

        loader = unittest.TestLoader()
        suite = loader.discover(start_dir=str(ROOT / "tests"), top_level_dir=str(ROOT))
        self.assertEqual(loader.errors, [], f"test discovery failed: {loader.errors}")
        self.assertEqual(
            int(claimed.group(1)), suite.countTestCases(),
            "REPORT.md's test count is stale -- update it to match the suite",
        )


if __name__ == "__main__":
    unittest.main()
