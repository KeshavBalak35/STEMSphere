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

RESEARCH_URLS = set(json.loads(
    (Path(__file__).resolve().parent.parent / "nmrx" / "data" / "research_urls.json").read_text()
)["urls"])


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

    def test_no_source_claims_verified_rights(self):
        """The research itself states there were no live checks, so nothing is 'verified'."""
        for s in self.registry:
            with self.subTest(source=s.id):
                self.assertNotEqual(s.rights_status, "open_verified")

    def test_harvestable_is_stricter_than_the_harvest_policy_field(self):
        """No provider prohibition is not the same as having the rights to use the data."""
        allowed = {s.id for s in self.registry.harvest_policy_allows()}
        harvestable = {s.id for s in self.registry.harvestable()}
        self.assertTrue(harvestable < allowed,
                        "harvestable() must exclude sources whose licence nobody has read")
        for s in self.registry.harvestable():
            with self.subTest(source=s.id):
                self.assertTrue(s.rights_established)

    def test_share_alike_obligations_are_machine_readable(self):
        """Copyleft must not live only in prose -- an exporter has to be able to see it."""
        for source_id in ("chembl", "drugcentral", "ord", "gtopdb"):
            with self.subTest(source=source_id):
                self.assertTrue(self.registry[source_id].has_share_alike)

    def test_share_alike_sources_do_not_read_as_plainly_commercial(self):
        for s in self.registry:
            if s.has_share_alike:
                with self.subTest(source=s.id):
                    self.assertNotEqual(s.commercial_use, "yes")

    def test_documented_overlaps_are_data_not_prose(self):
        self.assertIn("massbank", self.registry["mona"].republishes)
        self.assertIn("chembl", self.registry["bindingdb"].republishes)
        self.assertIn("rcsb", self.registry["pdbe"].overlaps_with)

    def test_searchable_is_not_assumed_calculable(self):
        """The map warns that extra databases do not extend the engine's validated domain."""
        for source_id in ("cod", "materialsproject", "nomad", "csd"):
            with self.subTest(source=source_id):
                self.assertIs(self.registry[source_id].engine_supported, False)

    def test_a_legal_prohibition_is_not_stored_as_a_rate_limit(self):
        """A consumer reading documented_rate_limit as a throttle must not meet a no-robots rule."""
        limit = self.registry["sdbs"].raw["access"].get("documented_rate_limit")
        self.assertFalse(limit and "prohibit" in str(limit).lower())
        self.assertIn("prohibit", self.registry["sdbs"].raw["access"]["prohibitions"].lower())

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
        """No endpoint may be composed out of thin air.

        Checked against nmrx/data/research_urls.json, which is committed, so this guarantee
        does not quietly turn into a skip once the original uploads are gone.
        """
        invented = []
        for s in load_registry():
            for route in s.routes():
                url = (route.get("url") or "").rstrip("/")
                if not url or route.get("provenance") == "inferred":
                    continue
                if url not in RESEARCH_URLS:
                    invented.append((s.id, url))
        self.assertEqual(invented, [], f"documented routes not found in the research material: {invented}")

    def test_the_research_url_list_is_present_and_substantial(self):
        """If this file goes missing the traceability guarantee is gone, not merely skipped."""
        self.assertGreater(len(RESEARCH_URLS), 100)


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


class TestVocabularyIsDefined(unittest.TestCase):
    """An invented term with no definition is how two readers quietly disagree."""

    @classmethod
    def setUpClass(cls):
        import json
        from pathlib import Path
        cls.vocab = json.loads(
            (Path(__file__).resolve().parent.parent / "nmrx" / "data" / "vocabulary.json").read_text()
        )
        cls.registry = load_registry()

    def _defined(self, section):
        return {k for k in self.vocab[section] if not k.startswith("_")}

    def test_every_tier_in_use_is_defined(self):
        used = {s.tier for s in self.registry}
        self.assertTrue(used <= self._defined("nmrx_tier"), used - self._defined("nmrx_tier"))

    def test_every_status_in_use_is_defined(self):
        used = {s.status for s in self.registry}
        self.assertTrue(used <= self._defined("status"))

    def test_every_rights_status_in_use_is_defined(self):
        used = {s.rights_status for s in self.registry}
        self.assertTrue(used <= self._defined("rights.status"))

    def test_every_harvest_policy_in_use_is_defined(self):
        used = {s.harvest_policy for s in self.registry}
        self.assertTrue(used <= self._defined("harvest_policy"))

    def test_every_obligation_in_use_is_defined(self):
        used = {o for s in self.registry for o in s.obligations}
        self.assertTrue(used <= self._defined("rights.obligations"),
                        used - self._defined("rights.obligations"))

    def test_every_commercial_use_value_in_use_is_defined(self):
        used = {s.commercial_use for s in self.registry}
        self.assertTrue(used <= self._defined("rights.commercial_use"))

    def test_the_vocabulary_records_that_nothing_is_verified(self):
        self.assertIn("_no_verified_value", self.vocab["rights.status"])
        self.assertNotIn("open_verified", self.vocab["rights.status"])

    def test_the_vocabulary_warns_harvest_policy_is_not_permission(self):
        note = self.vocab["harvest_policy"]["_meaning"]
        self.assertIn("never overrides", note.lower())
