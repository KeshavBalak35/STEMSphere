"""The transport must enforce caps while the body is arriving, and log every attempt."""

import io
import unittest
import urllib.error

from nmrx.sources.http import BoundedHttpClient, RequestLog
from nmrx.sources.policy import load_policy

GRANTED = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/1/JSON"


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json"):
        super().__init__(body)
        self.status = status

        class _H(dict):
            def get(self, k, default=None):
                return {"Content-Type": content_type}.get(k, default)
        self.headers = _H()

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _FakeOpener:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.calls = []

    def open(self, req, timeout=None):
        self.calls.append(req.full_url)
        if self._raises is not None:
            raise self._raises
        return self._response


def _client(policy=None, **opener_kw):
    policy = policy or load_policy()
    opener = _FakeOpener(**opener_kw)
    client = BoundedHttpClient(policy, opener_factory=lambda: opener, clock=lambda: 0.0)
    client.budget.caps.min_seconds_between_requests_per_host = 0.0
    return client, opener


class TestSuccessPath(unittest.TestCase):
    def test_a_granted_host_is_fetched_and_logged(self):
        body = b'{"ok": true}'
        client, opener = _client(response=_FakeResponse(body))
        attempt = client.get(GRANTED, source_id="pubchem", purpose="identity")
        self.assertEqual(attempt.outcome, "ok")
        self.assertEqual(attempt.status, 200)
        self.assertEqual(attempt.bytes_downloaded, len(body))
        self.assertEqual(attempt.body, body)
        self.assertEqual(opener.calls, [GRANTED])
        self.assertEqual(client.log.total_bytes(), len(body))


class TestCapsAreRealCeilings(unittest.TestCase):
    def test_an_oversized_body_is_abandoned_mid_read(self):
        """The cap must stop the transfer, not merely measure it afterwards."""
        client, _ = _client(response=_FakeResponse(b"x" * 200_000))
        attempt = client.get(GRANTED, source_id="pubchem", purpose="big", max_bytes=1024)
        self.assertEqual(attempt.outcome, "cap_exceeded")
        self.assertTrue(attempt.truncated)
        self.assertEqual(attempt.reason_code, "RESPONSE_BYTE_CAP")
        # read in 16 KiB chunks, so it stops within one chunk of the cap
        self.assertLess(attempt.bytes_downloaded, 200_000)

    def test_the_job_request_cap_stops_further_calls(self):
        client, opener = _client(response=_FakeResponse(b"{}"))
        client.budget.caps.max_requests_per_job = 1
        first = client.get(GRANTED, source_id="pubchem", purpose="one")
        second = client.get(GRANTED, source_id="pubchem", purpose="two")
        self.assertEqual(first.outcome, "ok")
        self.assertEqual(second.outcome, "policy_denied")
        self.assertEqual(second.reason_code, "JOB_REQUEST_CAP")
        self.assertEqual(len(opener.calls), 1, "the capped request must not reach the network")


class TestDenialsNeverOpenASocket(unittest.TestCase):
    def test_an_ungranted_host_is_refused_before_connecting(self):
        client, opener = _client(response=_FakeResponse(b"{}"))
        attempt = client.get("https://zenodo.org/api/records", purpose="x")
        self.assertEqual(attempt.outcome, "policy_denied")
        self.assertEqual(attempt.reason_code, "HOST_NOT_GRANTED")
        self.assertEqual(opener.calls, [], "no request may be made for a denied host")

    def test_a_prohibited_host_is_refused_before_connecting(self):
        client, opener = _client(response=_FakeResponse(b"{}"))
        attempt = client.get("https://sdbs.db.aist.go.jp/x", purpose="x")
        self.assertEqual(attempt.reason_code, "HOST_PROHIBITED")
        self.assertEqual(opener.calls, [])

    def test_denials_are_still_logged(self):
        client, _ = _client(response=_FakeResponse(b"{}"))
        client.get("https://zenodo.org/api/records", purpose="x")
        self.assertEqual(client.log.counts_by_outcome()["policy_denied"], 1)


class TestFailuresAreReportedNotRaised(unittest.TestCase):
    def test_a_network_error_becomes_a_recorded_attempt(self):
        err = urllib.error.URLError("CONNECT tunnel failed, response 403")
        client, _ = _client(raises=err)
        attempt = client.get(GRANTED, source_id="pubchem", purpose="probe")
        self.assertEqual(attempt.outcome, "network_error")
        self.assertIn("403", attempt.error)
        self.assertEqual(attempt.bytes_downloaded, 0)

    def test_an_http_error_becomes_a_recorded_attempt(self):
        err = urllib.error.HTTPError(GRANTED, 503, "Service Unavailable", None, None)
        client, _ = _client(raises=err)
        attempt = client.get(GRANTED, source_id="pubchem", purpose="probe")
        self.assertEqual(attempt.outcome, "http_error")
        self.assertEqual(attempt.status, 503)


class TestRedirects(unittest.TestCase):
    def test_a_redirect_to_another_host_is_not_followed(self):
        """SourceForge and BindingDB both redirect to hosts nobody granted."""
        class _Headers(dict):
            def get(self, k, default=None):
                return {"Location": "https://downloads.sourceforge.net/x"}.get(k, default)

        err = urllib.error.HTTPError(GRANTED, 302, "Found", _Headers(), None)
        client, _ = _client(raises=err)
        attempt = client.get(GRANTED, source_id="pubchem", purpose="probe")
        self.assertEqual(attempt.reason_code, "REDIRECT_NOT_FOLLOWED")
        self.assertIn("downloads.sourceforge.net", attempt.error)


class TestLogSerialisation(unittest.TestCase):
    def test_log_round_trips_to_json(self):
        import json
        import tempfile
        from pathlib import Path

        client, _ = _client(response=_FakeResponse(b'{"a":1}'))
        client.get(GRANTED, source_id="pubchem", purpose="identity")
        with tempfile.TemporaryDirectory() as tmp:
            path = client.log.write_json(Path(tmp) / "log.json", extra={"run": "test"})
            doc = json.loads(path.read_text())
        self.assertEqual(doc["run"], "test")
        self.assertEqual(doc["attempt_count"], 1)
        self.assertEqual(doc["attempts"][0]["url"], GRANTED)


if __name__ == "__main__":
    unittest.main()
