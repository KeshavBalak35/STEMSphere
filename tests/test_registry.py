"""The registry is a research directory. These tests keep it honest."""

import json
import unittest
from pathlib import Path

from nmrx.sources.policy import load_policy
from nmrx.sources.registry import (
    HARVEST_POLICY_VALUES,
    RIGHTS_STATUS_VALUES,
    STATUS_VALUES,
    TIER_VALUES,
    load_registry,
)

UPLOADED = Path("/root/.claude/uploads/8e17b3ed-5e1d-510c-b487-8bd3f4a0e311"
                "/958a19a8-NMRx_Chemical_Source_Registry.json")


class TestRegistryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_all_fifty_sources_are_present(self):
        self.assertEqual(len(self.registry), 50)

    def test_ids_are_unique(self):
        ids = self.registry.ids()
        self.assertEqual(len(ids), len(set(ids)))

    def test_registry_validates_against_its_own_contract(self):
        self.assertEqual(self.registry.validate(), [])

    def test_enumerated_fields_stay_in_their_vocabularies(self):
        for s in self.registry:
            with self.subTest(source=s.id):
                self.assertIn(s.tier, TIER_VALUES)
                self.assertIn(s.status, STATUS_VALUES)
                self.assertIn(s.rights_status, RIGHTS_STATUS_VALUES)
                self.assertIn(s.harvest_policy, HARVEST_POLICY_VALUES)

    def test_nothing_claims_ingestion_approval(self):
        """The research map explicitly grants no ingestion permission."""
        for s in self.registry:
            with self.subTest(source=s.id):
                self.assertFalse(s.raw["automated_ingestion_approved"])

    def test_nothing_claims_to_be_live_tested(self):
        """No host is reachable, so no entry may claim live verification."""
        self.assertEqual(self.registry.by_status("live_tested"), [])


class TestRightsHonesty(unittest.TestCase):
    """Sources the research explicitly hedged must not be upgraded to a clean licence."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    HEDGED = ("nmrshiftdb2", "bmrb", "rruff", "qcarchive", "nmrbank")

    def test_hedged_sources_keep_an_unverified_rights_status(self):
        for source_id in self.HEDGED:
            with self.subTest(source=source_id):
                self.assertIn(
                    self.registry[source_id].rights_status,
                    ("unverified", "open_unverified", "per_record"),
                    "the map could not read this licence; it must not read as settled",
                )

    def test_hedged_sources_do_not_assert_commercial_use(self):
        for source_id in self.HEDGED:
            with self.subTest(source=source_id):
                self.assertNotEqual(self.registry[source_id].commercial_use, "yes")

    def test_non_commercial_sources_are_marked(self):
        self.assertEqual(self.registry["cas_common"].commercial_use, "no")


class TestHarvestPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_sdbs_harvesting_is_prohibited(self):
        """SDBS's disclaimer forbids robot collection. This is not negotiable."""
        self.assertEqual(self.registry["sdbs"].harvest_policy, "prohibited")

    def test_licensed_sources_require_a_licence(self):
        for source_id in ("drugbank", "spectrabase", "csd", "gtopdb", "nist", "cas_common"):
            with self.subTest(source=source_id):
                self.assertIn(
                    self.registry[source_id].harvest_policy,
                    ("licence_required", "manual_only", "prohibited"),
                )


class TestRouteProvenance(unittest.TestCase):
    def test_every_route_declares_documented_or_inferred(self):
        for s in load_registry():
            for route in s.routes():
                with self.subTest(source=s.id, url=route.get("url")):
                    self.assertIn(route.get("provenance"), ("documented", "inferred"))

    def test_routes_only_cite_urls_that_exist_in_the_research_material(self):
        """No endpoint may be composed out of thin air."""
        if not UPLOADED.exists():
            self.skipTest("original research registry not available in this environment")
        corpus = UPLOADED.read_text()
        map_path = UPLOADED.with_name("18abb5f3-NMRx_Chemical_Database_Map.md")
        if map_path.exists():
            corpus += map_path.read_text()

        invented = []
        for s in load_registry():
            for route in s.routes():
                url = (route.get("url") or "").rstrip("/")
                if not url or route.get("provenance") == "inferred":
                    continue
                if url not in corpus:
                    invented.append((s.id, url))
        self.assertEqual(invented, [], f"documented routes not found in the research material: {invented}")


class TestRegistryAgreesWithPolicy(unittest.TestCase):
    """The two files must not drift apart."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()
        cls.policy = load_policy()

    def test_every_policy_source_id_exists_in_the_registry(self):
        known = set(self.registry.ids()) | {"ebi_shared"}
        for grant in self.policy.granted_hosts():
            with self.subTest(host=grant.host):
                self.assertIn(grant.source_id, known)

    def test_every_prohibited_source_is_prohibited_in_the_registry_too(self):
        for entry in self.policy.prohibited_hosts():
            with self.subTest(host=entry["host"]):
                self.assertEqual(self.registry[entry["source_id"]].harvest_policy, "prohibited")

    def test_granted_hosts_appear_among_their_sources_hosts(self):
        for grant in self.policy.granted_hosts():
            if grant.source_id == "ebi_shared":
                continue
            with self.subTest(host=grant.host):
                self.assertIn(grant.host, self.registry[grant.source_id].hosts())


class TestQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_nmr_sources_include_the_priority_four(self):
        nmr_ids = {s.id for s in self.registry.nmr_sources()}
        for source_id in ("nmrshiftdb2", "bmrb", "nmrxiv", "chemotion"):
            with self.subTest(source=source_id):
                self.assertIn(source_id, nmr_ids)

    def test_measured_nmr_excludes_pure_prediction_sources(self):
        measured = {s.id for s in self.registry.measured_nmr_sources()}
        self.assertNotIn("qm9", measured)

    def test_harvestable_excludes_prohibited_and_licensed(self):
        harvestable = {s.id for s in self.registry.harvestable()}
        for source_id in ("sdbs", "drugbank", "spectrabase", "csd"):
            with self.subTest(source=source_id):
                self.assertNotIn(source_id, harvestable)


if __name__ == "__main__":
    unittest.main()
