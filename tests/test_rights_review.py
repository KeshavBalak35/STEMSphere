"""The registry must never be more permissive than the independent rights review."""

import json
import unittest
from pathlib import Path

from nmrx.sources.policy import load_policy
from nmrx.sources.registry import load_registry

REVIEW_PATH = Path(__file__).resolve().parent.parent / "nmrx" / "data" / "rights_review.json"


class TestReviewCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads(REVIEW_PATH.read_text())
        cls.registry = load_registry()
        cls.buckets = cls.review["buckets"]

    def test_every_source_is_bucketed_exactly_once(self):
        seen = [sid for ids in self.buckets.values() for sid in ids]
        self.assertEqual(len(seen), 50)
        self.assertEqual(len(set(seen)), 50)

    def test_bucketed_ids_are_real_registry_ids(self):
        known = set(self.registry.ids())
        for bucket, ids in self.buckets.items():
            for sid in ids:
                with self.subTest(bucket=bucket, source=sid):
                    self.assertIn(sid, known)


class TestRegistryDoesNotOverstateRights(unittest.TestCase):
    """The direction that matters: the registry may be stricter, never looser."""

    @classmethod
    def setUpClass(cls):
        cls.review = json.loads(REVIEW_PATH.read_text())
        cls.registry = load_registry()
        cls.buckets = cls.review["buckets"]

    def test_non_commercial_sources_never_claim_commercial_use(self):
        for sid in self.buckets["non_commercial_only"]:
            with self.subTest(source=sid):
                self.assertNotEqual(self.registry[sid].commercial_use, "yes")

    def test_licence_required_sources_never_claim_open_verified_rights(self):
        for sid in self.buckets["licence_or_account_required"]:
            with self.subTest(source=sid):
                self.assertNotEqual(self.registry[sid].rights_status, "open_verified")

    def test_unverified_sources_never_claim_open_verified_rights(self):
        for sid in self.buckets["rights_unverified"]:
            with self.subTest(source=sid):
                self.assertNotEqual(
                    self.registry[sid].rights_status, "open_verified",
                    "the review could not establish this licence; the registry must not settle it",
                )

    def test_prohibited_sources_are_prohibited_in_the_registry(self):
        for sid in self.buckets["harvesting_prohibited"]:
            with self.subTest(source=sid):
                self.assertEqual(self.registry[sid].harvest_policy, "prohibited")

    def test_the_nmr_priority_sources_all_have_unsettled_rights(self):
        """The headline risk: our best NMR data has our least settled rights."""
        unverified = set(self.buckets["rights_unverified"])
        for sid in ("nmrshiftdb2", "bmrb", "nmrxiv", "chemotion"):
            with self.subTest(source=sid):
                self.assertIn(sid, unverified)


class TestShareAlikeIsTracked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads(REVIEW_PATH.read_text())

    def test_share_alike_sources_are_listed(self):
        blob = " ".join(self.review["share_alike_contagion"])
        for name in ("ChEMBL", "BindingDB", "DrugCentral", "Chemotion", "MassBank"):
            with self.subTest(name=name):
                self.assertIn(name, blob)

    def test_the_odbl_source_is_called_out(self):
        blob = " ".join(self.review["share_alike_contagion"])
        self.assertIn("ODbL", blob)

    def test_known_licence_traps_are_recorded(self):
        blob = " ".join(self.review["traps"]).lower()
        for trap in ("code repo licence", "public domain", "footer", "metadata cc0"):
            with self.subTest(trap=trap):
                self.assertIn(trap, blob)


class TestPolicyAgreesWithTheReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads(REVIEW_PATH.read_text())
        cls.policy = load_policy()

    def test_no_granted_host_belongs_to_a_prohibited_or_nc_source(self):
        forbidden = set(self.review["buckets"]["harvesting_prohibited"]) | \
                    set(self.review["buckets"]["non_commercial_only"])
        for grant in self.policy.granted_hosts():
            with self.subTest(host=grant.host):
                self.assertNotIn(grant.source_id, forbidden)

    def test_licence_required_sources_have_a_recorded_blocker(self):
        for sid in self.review["buckets"]["licence_or_account_required"]:
            with self.subTest(source=sid):
                self.assertIsNotNone(
                    self.policy.credential_blocker(sid),
                    f"{sid} needs a licence or account but the policy records no blocker",
                )


if __name__ == "__main__":
    unittest.main()
