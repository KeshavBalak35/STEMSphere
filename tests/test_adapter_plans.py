"""The shipped adapter plans must stay honest about what has and has not been confirmed."""

import json
import unittest
from pathlib import Path

from nmrx.adapters.base import MAPPINGS_DIR, AdapterPlan, SchemaUnconfirmed, SourceAdapter, available_plans
from nmrx.sources.policy import load_policy
from nmrx.sources.registry import load_registry

PLAN_IDS = available_plans()
RESEARCH_URLS = set(json.loads(
    (Path(__file__).resolve().parent.parent / "nmrx" / "data" / "research_urls.json").read_text()
)["urls"])


class TestPlansExist(unittest.TestCase):
    def test_the_priority_nmr_sources_all_have_plans(self):
        for source_id in ("nmrshiftdb2", "bmrb", "nmrxiv", "chemotion"):
            with self.subTest(source=source_id):
                self.assertIn(source_id, PLAN_IDS)

    def test_every_plan_loads(self):
        for source_id in PLAN_IDS:
            with self.subTest(source=source_id):
                self.assertEqual(AdapterPlan.load(source_id).source_id, source_id)


class TestNothingClaimsConfirmation(unittest.TestCase):
    """No host is reachable, so no schema can have been confirmed."""

    def test_no_plan_claims_a_confirmed_schema(self):
        for source_id in PLAN_IDS:
            with self.subTest(source=source_id):
                self.assertFalse(AdapterPlan.load(source_id).schema_confirmed)

    def test_every_plan_records_why_it_is_unconfirmed(self):
        for source_id in PLAN_IDS:
            with self.subTest(source=source_id):
                unknowns = AdapterPlan.load(source_id).blocking_unknowns
                self.assertTrue(unknowns)
                self.assertTrue(any("blocked at CONNECT" in u for u in unknowns))

    def test_live_fetch_is_refused_for_every_plan(self):
        for source_id in PLAN_IDS:
            with self.subTest(source=source_id):
                adapter = SourceAdapter.load(source_id, client=object())
                route = adapter.plan.routes[0]
                with self.assertRaises(SchemaUnconfirmed):
                    adapter.fetch(route.purpose)


class TestRouteProvenance(unittest.TestCase):
    def test_every_route_is_documented_or_inferred(self):
        for source_id in PLAN_IDS:
            for route in AdapterPlan.load(source_id).routes:
                with self.subTest(source=source_id, purpose=route.purpose):
                    self.assertIn(route.provenance, ("documented", "inferred"))

    def test_inferred_routes_say_what_is_unconfirmed(self):
        for source_id in PLAN_IDS:
            for route in AdapterPlan.load(source_id).routes:
                if route.provenance == "inferred":
                    with self.subTest(source=source_id, purpose=route.purpose):
                        self.assertTrue(route.must_confirm_live)

    def test_documented_route_urls_appear_in_the_research_material(self):
        """A 'documented' URL must be traceable, not composed.

        Checked against the committed URL list, so this cannot degrade into a skip.
        """
        invented = []
        for source_id in PLAN_IDS:
            for route in AdapterPlan.load(source_id).routes:
                if route.provenance != "documented":
                    continue
                if route.url_template.rstrip("/") not in RESEARCH_URLS:
                    invented.append((source_id, route.url_template))
        self.assertEqual(invented, [], f"documented routes not traceable to the research: {invented}")

    def test_no_route_template_targets_a_prohibited_host(self):
        policy = load_policy()
        prohibited = {p["host"] for p in policy.prohibited_hosts()}
        for source_id in PLAN_IDS:
            for route in AdapterPlan.load(source_id).routes:
                with self.subTest(source=source_id, url=route.url_template):
                    for host in prohibited:
                        self.assertNotIn(host, route.url_template)


class TestPlansAgreeWithTheRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_every_plan_matches_a_registry_source(self):
        for source_id in PLAN_IDS:
            with self.subTest(source=source_id):
                self.assertIsNotNone(self.registry.get(source_id))

    def test_required_hosts_are_known_to_the_registry(self):
        for source_id in PLAN_IDS:
            source = self.registry[source_id]
            known = set(source.hosts())
            for host in AdapterPlan.load(source_id).hosts_required:
                with self.subTest(source=source_id, host=host):
                    self.assertIn(host, known)

    def test_plans_carry_the_sources_specific_caution(self):
        """Each plan must repeat the trap that applies to it, not a generic note."""
        expectations = {
            "nmrshiftdb2": "CALCULATED",
            "bmrb": "theoretical",
            "nmrxiv": "does NOT guarantee an assigned spectrum",
            "chemotion": "not every spectrum has atom assignments",
            "pubchem": "too broad",
        }
        for source_id, needle in expectations.items():
            with self.subTest(source=source_id):
                self.assertIn(needle, AdapterPlan.load(source_id).notes)


class TestProvisionalMappingsAreLabelled(unittest.TestCase):
    def test_a_provisional_mapping_says_so(self):
        for source_id in PLAN_IDS:
            mapping = AdapterPlan.load(source_id).record_mapping
            with self.subTest(source=source_id):
                self.assertIn("provisional", mapping.get("_status", ""))

    def test_a_provisional_mapping_still_runs_end_to_end(self):
        """The engine must be exercisable before any schema is confirmed."""
        payload = {
            "id": "SYN-1", "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-N", "nucleus": "13C",
            "solvent": "CDCl3", "temperature_k": 298.0, "reference": "TMS", "atom_count": 2,
            "peaks": [{"atom": 0, "element": "C", "ppm": 10.0},
                      {"atom": 1, "element": "C", "ppm": 20.0}],
        }
        records = SourceAdapter.load("nmrshiftdb2").parse(payload)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(records[0].shifts), 2)
        self.assertTrue(records[0].fully_assigned)


if __name__ == "__main__":
    unittest.main()
