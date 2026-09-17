"""The access policy gate is the thing standing between a research directory and a crawl."""

import unittest

from nmrx.sources.policy import PolicyDenied, load_policy


class TestHostGrants(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def test_pilot_hosts_are_granted(self):
        expected = {
            "pubchem.ncbi.nlm.nih.gov",
            "nmrshiftdb.nmr.uni-koeln.de",
            "www.ebi.ac.uk",
            "data.rcsb.org",
            "search.rcsb.org",
            "www.bindingdb.org",
        }
        self.assertEqual({g.host for g in self.policy.granted_hosts()}, expected)

    def test_registry_membership_is_not_permission(self):
        """A source can be fully documented and still not be callable."""
        with self.assertRaises(PolicyDenied) as ctx:
            self.policy.authorize("https://zenodo.org/api/records")
        self.assertEqual(ctx.exception.reason_code, "HOST_NOT_GRANTED")

    def test_hostname_match_is_exact_not_suffix(self):
        """www.bindingdb.org being granted must not silently grant its siblings.

        The map flags bindingdb.org and ww.bindingdb.org as distinct hosts used by the
        provider's own docs; a suffix match here would widen the pilot without anyone
        deciding to.
        """
        self.policy.authorize("https://www.bindingdb.org/x")  # granted
        for host in ("bindingdb.org", "ww.bindingdb.org", "evil-bindingdb.org"):
            with self.subTest(host=host), self.assertRaises(PolicyDenied) as ctx:
                self.policy.authorize(f"https://{host}/x")
            self.assertEqual(ctx.exception.reason_code, "HOST_NOT_GRANTED")

    def test_expansion_candidates_are_assessed_but_not_granted(self):
        for host in ("bmrb.io", "api.bmrb.io", "nmrxiv.org", "www.chemotion-repository.net"):
            with self.subTest(host=host), self.assertRaises(PolicyDenied) as ctx:
                self.policy.authorize(f"https://{host}/api/x")
            self.assertEqual(ctx.exception.reason_code, "HOST_CANDIDATE_NOT_GRANTED")

    def test_sdbs_is_permanently_prohibited(self):
        """SDBS forbids robot collection; this must never degrade to 'not yet granted'."""
        with self.assertRaises(PolicyDenied) as ctx:
            self.policy.authorize("https://sdbs.db.aist.go.jp/Htmls/x.html")
        self.assertEqual(ctx.exception.reason_code, "HOST_PROHIBITED")

    def test_licensed_sources_refuse_before_the_network(self):
        for source_id in ("drugbank", "cas_common", "spectrabase", "csd", "sabiork", "gtopdb", "nist"):
            with self.subTest(source_id=source_id):
                self.assertIsNotNone(self.policy.credential_blocker(source_id))

    def test_plain_http_is_refused(self):
        with self.assertRaises(PolicyDenied) as ctx:
            self.policy.authorize("http://pubchem.ncbi.nlm.nih.gov/x")
        self.assertEqual(ctx.exception.reason_code, "SCHEME_NOT_HTTPS")

    def test_source_host_mismatch_is_caught(self):
        with self.assertRaises(PolicyDenied) as ctx:
            self.policy.authorize("https://pubchem.ncbi.nlm.nih.gov/x", source_id="nmrshiftdb2")
        self.assertEqual(ctx.exception.reason_code, "SOURCE_HOST_MISMATCH")

    def test_ebi_host_is_shared_across_its_three_services(self):
        """One host serves ChEMBL, ChEBI and UniChem; all three must pass."""
        for source_id in ("chembl", "chebi", "unichem"):
            with self.subTest(source_id=source_id):
                grant = self.policy.authorize("https://www.ebi.ac.uk/chembl/api/data/molecule",
                                              source_id=source_id)
                self.assertEqual(grant.source_id, "ebi_shared")


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def test_request_cap_is_enforced(self):
        budget = self.policy.new_budget()
        budget.requests_made = budget.caps.max_requests_per_job
        with self.assertRaises(PolicyDenied) as ctx:
            budget.check_before("pubchem.ncbi.nlm.nih.gov")
        self.assertEqual(ctx.exception.reason_code, "JOB_REQUEST_CAP")

    def test_job_byte_cap_is_enforced(self):
        budget = self.policy.new_budget()
        budget.bytes_downloaded = budget.caps.max_bytes_per_job
        with self.assertRaises(PolicyDenied) as ctx:
            budget.check_before("pubchem.ncbi.nlm.nih.gov")
        self.assertEqual(ctx.exception.reason_code, "JOB_BYTE_CAP")

    def test_response_cap_is_enforced(self):
        budget = self.policy.new_budget()
        with self.assertRaises(PolicyDenied) as ctx:
            budget.check_response_size(budget.caps.max_bytes_per_response + 1)
        self.assertEqual(ctx.exception.reason_code, "RESPONSE_BYTE_CAP")

    def test_throttle_spaces_requests_on_one_host(self):
        budget = self.policy.new_budget()
        slept = []
        fake_now = [0.0]
        budget.throttle("h", sleep=slept.append, now=lambda: fake_now[0])
        waited = budget.throttle("h", sleep=slept.append, now=lambda: fake_now[0])
        self.assertGreater(waited, 0.0)
        self.assertTrue(slept)

    def test_throttle_does_not_couple_separate_hosts(self):
        budget = self.policy.new_budget()
        fake_now = [0.0]
        budget.throttle("a", sleep=lambda s: None, now=lambda: fake_now[0])
        waited = budget.throttle("b", sleep=lambda s: None, now=lambda: fake_now[0])
        self.assertEqual(waited, 0.0)

    def test_caps_are_flagged_as_unconfirmed_defaults(self):
        """These numbers were chosen here, not handed down. That must stay visible."""
        self.assertEqual(self.policy.caps.provenance, "proposed_default_awaiting_user_confirmation")


if __name__ == "__main__":
    unittest.main()


class TestHostScopeIsDocumented(unittest.TestCase):
    """Granting a host can silently grant more than its name suggests."""

    def setUp(self):
        self.policy = load_policy()
        self.by_host = {g.host: g for g in self.policy.granted_hosts()}

    def test_every_granted_host_carries_a_scope_caution(self):
        for host, grant in self.by_host.items():
            with self.subTest(host=host):
                self.assertTrue(grant.hostname_caution,
                                f"{host} has no recorded caution about what it does and does not cover")

    def test_the_ebi_scope_warning_names_the_services_it_also_grants(self):
        caution = self.by_host["www.ebi.ac.uk"].hostname_caution
        for service in ("ChEMBL", "ChEBI", "UniChem", "PDBe", "Europe PMC"):
            with self.subTest(service=service):
                self.assertIn(service, caution)

    def test_the_bindingdb_caution_names_all_three_spellings(self):
        caution = self.by_host["www.bindingdb.org"].hostname_caution
        self.assertIn("ww.bindingdb.org", caution)
        self.assertIn("no www", caution)

    def test_documented_but_ungranted_bulk_hosts_are_all_refused(self):
        """Every host named as 'documented but not granted' must actually be refused."""
        import json
        from pathlib import Path
        doc = json.loads((Path(__file__).resolve().parent.parent / "nmrx" / "data"
                          / "access_policy.json").read_text())
        hosts = [h["host"] for h in doc["pilot"]["_documented_but_not_granted"]["hosts"]]
        self.assertGreaterEqual(len(hosts), 6)
        for host in hosts:
            with self.subTest(host=host), self.assertRaises(PolicyDenied) as ctx:
                self.policy.authorize(f"https://{host}/x")
            self.assertEqual(ctx.exception.reason_code, "HOST_NOT_GRANTED")
