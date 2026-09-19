"""The probe must tell three kinds of 'no' apart, and must not re-probe a blocked host."""

import unittest
import urllib.error

from nmrx.sources.http import Attempt, BoundedHttpClient
from nmrx.sources.policy import load_policy
from nmrx.sources.probe import ProbeStep, classify, load_plan, run

GRANTED = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/JSON"


def _attempt(outcome, error=None, status=None):
    return Attempt(url=GRANTED, host="pubchem.ncbi.nlm.nih.gov", source_id="pubchem",
                   purpose="t", started_at="now", outcome=outcome, error=error, status=status)


class TestClassification(unittest.TestCase):
    def test_a_proxy_403_is_an_environment_block_not_a_service_failure(self):
        for text in ("CONNECT tunnel failed, response 403",
                     "Tunnel connection failed: 403 Forbidden",
                     "URLError: <urlopen error Tunnel connection failed: 403 Forbidden>"):
            with self.subTest(text=text):
                self.assertEqual(
                    classify(_attempt("network_error", error=text)),
                    "blocked_by_environment_network_policy",
                )

    def test_a_project_denial_is_reported_separately(self):
        """Our own refusal says nothing about whether the host is reachable."""
        self.assertEqual(classify(_attempt("policy_denied", error="not granted")),
                         "refused_by_project_policy")

    def test_reaching_the_service_is_distinguished_from_being_blocked(self):
        self.assertEqual(classify(_attempt("http_error", status=404)),
                         "reached_service_http_error")
        self.assertEqual(classify(_attempt("ok", status=200)), "reachable")

    def test_an_ordinary_network_failure_is_not_called_a_block(self):
        self.assertEqual(classify(_attempt("network_error", error="timed out")),
                         "network_failure")


class _StubOpener:
    def __init__(self, exc):
        self.exc = exc
        self.calls = []

    def open(self, req, timeout=None):
        self.calls.append(req.full_url)
        raise self.exc


class TestBlockedHostIsNotReProbed(unittest.TestCase):
    def test_further_steps_on_a_blocked_host_are_skipped(self):
        """Standing instruction: do not repeat an unchanged blocked probe."""
        policy = load_policy()
        opener = _StubOpener(urllib.error.URLError("Tunnel connection failed: 403 Forbidden"))
        client = BoundedHttpClient(policy, opener_factory=lambda: opener, clock=lambda: 0.0)
        client.budget.caps.min_seconds_between_requests_per_host = 0.0

        steps = [
            ProbeStep("pubchem", "first", GRANTED),
            ProbeStep("pubchem", "second", GRANTED + "?x=1"),
            ProbeStep("pubchem", "third", GRANTED + "?x=2"),
        ]
        report = run(steps, policy=policy, client=client)

        self.assertEqual(report["steps_planned"], 3)
        self.assertEqual(report["steps_executed"], 1)
        self.assertEqual(len(opener.calls), 1, "a blocked host must be contacted only once")
        self.assertEqual(report["results"][1]["classification"], "skipped_host_already_blocked")
        self.assertEqual(report["blocked_hosts"], ["pubchem.ncbi.nlm.nih.gov"])

    def test_a_blocked_run_downloads_nothing(self):
        policy = load_policy()
        opener = _StubOpener(urllib.error.URLError("Tunnel connection failed: 403 Forbidden"))
        client = BoundedHttpClient(policy, opener_factory=lambda: opener, clock=lambda: 0.0)
        client.budget.caps.min_seconds_between_requests_per_host = 0.0
        report = run([ProbeStep("pubchem", "p", GRANTED)], policy=policy, client=client)
        self.assertEqual(report["total_bytes_downloaded"], 0)


class TestShippedPlan(unittest.TestCase):
    def test_the_plan_loads_and_targets_only_granted_hosts(self):
        policy = load_policy()
        granted = {g.host for g in policy.granted_hosts()}
        steps = load_plan()
        self.assertTrue(steps)
        for step in steps:
            with self.subTest(url=step.url):
                self.assertIn(policy.host_of(step.url), granted)

    def test_the_plan_covers_every_granted_host(self):
        policy = load_policy()
        probed = {policy.host_of(s.url) for s in load_plan()}
        self.assertEqual(probed, {g.host for g in policy.granted_hosts()})

    def test_the_plan_is_small(self):
        """A pilot probe is a reachability check, not a harvest."""
        self.assertLessEqual(len(load_plan()), 10)


class TestRecordedRun(unittest.TestCase):
    """The committed probe artifact must keep saying what actually happened."""

    def setUp(self):
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "nmrx" / "data" / "probes" / \
            "pilot_probe_2026-09-17.json"
        if not path.exists():
            self.skipTest("probe artifact not present")
        self.report = json.loads(path.read_text())

    def test_the_recorded_run_downloaded_zero_bytes(self):
        self.assertEqual(self.report["total_bytes_downloaded"], 0)

    def test_every_pilot_host_was_blocked_by_the_environment(self):
        self.assertEqual(
            self.report["classification_counts"].get("blocked_by_environment_network_policy"),
            self.report["steps_executed"],
        )


if __name__ == "__main__":
    unittest.main()
