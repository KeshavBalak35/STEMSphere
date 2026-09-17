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


class TestUrlGateCannotBeTricked(unittest.TestCase):
    """A string that merely looks like a granted host must not reach the network."""

    def setUp(self):
        self.policy = load_policy()

    def _deny(self, url, code):
        with self.assertRaises(PolicyDenied) as ctx:
            self.policy.authorize(url)
        self.assertEqual(ctx.exception.reason_code, code, f"for {url}")

    def test_userinfo_cannot_disguise_the_real_host(self):
        """https://granted.host@evil.com/ actually connects to evil.com.

        Denied either way -- the userinfo check happens to fire first. What matters is that
        it is never resolved to the grant whose name appears in the userinfo segment.
        """
        url = "https://pubchem.ncbi.nlm.nih.gov@evil.com/x"
        with self.assertRaises(PolicyDenied) as ctx:
            self.policy.authorize(url)
        self.assertIn(ctx.exception.reason_code, ("CREDENTIALS_IN_URL", "HOST_NOT_GRANTED"))

        # And with the userinfo check removed from the picture, the host still is not granted.
        with self.assertRaises(PolicyDenied) as ctx2:
            self.policy.authorize("https://evil.com/x")
        self.assertEqual(ctx2.exception.reason_code, "HOST_NOT_GRANTED")

    def test_embedded_credentials_are_refused(self):
        """No granted source is authenticated, and userinfo would land in the request log."""
        self._deny("https://user:pass@pubchem.ncbi.nlm.nih.gov/x", "CREDENTIALS_IN_URL")
        self._deny("https://user@pubchem.ncbi.nlm.nih.gov/x", "CREDENTIALS_IN_URL")

    def test_a_non_standard_port_is_refused(self):
        """A granted host on another port is a different service."""
        self._deny("https://pubchem.ncbi.nlm.nih.gov:8443/x", "PORT_NOT_443")

    def test_an_explicit_443_is_accepted(self):
        self.assertEqual(self.policy.authorize("https://pubchem.ncbi.nlm.nih.gov:443/x").source_id,
                         "pubchem")

    def test_an_unparseable_port_is_refused(self):
        self._deny("https://pubchem.ncbi.nlm.nih.gov:99999/x", "BAD_PORT")

    def test_a_subdomain_suffix_does_not_match(self):
        self._deny("https://pubchem.ncbi.nlm.nih.gov.evil.com/x", "HOST_NOT_GRANTED")

    def test_case_is_normalised(self):
        self.assertEqual(self.policy.authorize("https://PubChem.NCBI.NLM.NIH.gov/x").source_id,
                         "pubchem")

    def test_a_trailing_dot_cannot_dodge_the_prohibition(self):
        """'sdbs.db.aist.go.jp.' resolves the same but would not match by string."""
        for url in ("https://sdbs.db.aist.go.jp./x", "https://SDBS.DB.AIST.GO.JP./x"):
            with self.subTest(url=url):
                self._deny(url, "HOST_PROHIBITED")

    def test_a_trailing_dot_still_matches_a_grant(self):
        self.assertEqual(self.policy.authorize("https://pubchem.ncbi.nlm.nih.gov./x").source_id,
                         "pubchem")

    def test_a_scheme_relative_url_is_refused(self):
        self._deny("//pubchem.ncbi.nlm.nih.gov/x", "SCHEME_NOT_HTTPS")
