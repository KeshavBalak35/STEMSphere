"""Bounded HTTP client. Every NMRx outbound request goes through here.

Guarantees:

* the policy gate runs before a socket is opened;
* per-host spacing is honoured;
* the response body is read incrementally and abandoned the moment it exceeds the
  per-response cap, so a cap is a real ceiling and not an after-the-fact measurement;
* a redirect to a host that is not itself granted is refused rather than followed;
* every attempt -- success, denial or failure -- is appended to a :class:`RequestLog`
  with the exact URL, status, byte count and error text, so the pilot can be reported
  in terms of what actually happened on the wire.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .policy import AccessPolicy, JobBudget, PolicyDenied

USER_AGENT = "NMRx-source-probe/0.1 (research; contact via project maintainer)"

#: Read chunk size. Small enough that the cap is enforced promptly on a large body.
_CHUNK = 16384


@dataclass
class Attempt:
    """One outbound attempt, recorded whether or not it reached the network."""

    url: str
    host: str
    source_id: Optional[str]
    purpose: str
    started_at: str
    outcome: str          # "ok" | "policy_denied" | "http_error" | "network_error" | "cap_exceeded"
    status: Optional[int] = None
    bytes_downloaded: int = 0
    content_type: Optional[str] = None
    elapsed_ms: Optional[int] = None
    error: Optional[str] = None
    reason_code: Optional[str] = None
    truncated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RequestLog:
    """Append-only record of everything a job attempted."""

    attempts: List[Attempt] = field(default_factory=list)

    def add(self, attempt: Attempt) -> Attempt:
        self.attempts.append(attempt)
        return attempt

    def total_bytes(self) -> int:
        return sum(a.bytes_downloaded for a in self.attempts)

    def counts_by_outcome(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for a in self.attempts:
            out[a.outcome] = out.get(a.outcome, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "attempt_count": len(self.attempts),
            "total_bytes_downloaded": self.total_bytes(),
            "counts_by_outcome": self.counts_by_outcome(),
            "attempts": [a.to_dict() for a in self.attempts],
        }

    def write_json(self, path: Path | str, extra: Optional[dict] = None) -> Path:
        payload = dict(extra or {})
        payload.update(self.to_dict())
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False)
            fh.write("\n")
        return path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects to the caller instead of following them silently."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BoundedHttpClient:
    """Policy-gated, byte-capped HTTPS client."""

    def __init__(
        self,
        policy: AccessPolicy,
        budget: Optional[JobBudget] = None,
        log: Optional[RequestLog] = None,
        opener_factory: Optional[Callable[[], urllib.request.OpenerDirector]] = None,
        clock: Callable[[], float] = None,
    ) -> None:
        self.policy = policy
        self.budget = budget or policy.new_budget()
        self.log = log or RequestLog()
        self._opener_factory = opener_factory or self._default_opener
        if clock is None:
            import time as _time

            clock = _time.monotonic
        self._clock = clock

    @staticmethod
    def _default_opener() -> urllib.request.OpenerDirector:
        # The environment supplies its own CA bundle via SSL_CERT_FILE / REQUESTS_CA_BUNDLE.
        # create_default_context() picks that up. Verification is never disabled.
        ctx = ssl.create_default_context()
        return urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            _NoRedirect(),
        )

    def get(
        self,
        url: str,
        *,
        source_id: Optional[str] = None,
        purpose: str = "",
        accept: str = "application/json",
        max_bytes: Optional[int] = None,
    ) -> Attempt:
        """Fetch ``url`` under policy. Returns the :class:`Attempt`; body is on ``.body``.

        Never raises for an ordinary HTTP or network failure -- the failure is recorded on
        the returned attempt so a probe run can report every host in one pass.
        :class:`PolicyDenied` is also captured rather than raised, for the same reason.
        """
        started = _utcnow()
        host = "(unparsed)"
        try:
            host = self.policy.host_of(url)
        except PolicyDenied as exc:
            att = Attempt(url=url, host=host, source_id=source_id, purpose=purpose,
                          started_at=started, outcome="policy_denied",
                          error=exc.message, reason_code=exc.reason_code)
            att.body = b""  # type: ignore[attr-defined]
            return self.log.add(att)

        try:
            self.policy.authorize(url, source_id=source_id)
            self.budget.check_before(host)
        except PolicyDenied as exc:
            att = Attempt(url=url, host=host, source_id=source_id, purpose=purpose,
                          started_at=started, outcome="policy_denied",
                          error=exc.message, reason_code=exc.reason_code)
            att.body = b""  # type: ignore[attr-defined]
            return self.log.add(att)

        # The effective ceiling is the tighter of the per-response cap and what the job
        # has left. `min` directly -- a falsy-zero fallback here would silently restore the
        # full cap at the exact moment the job budget ran out.
        cap = max_bytes if max_bytes is not None else self.budget.caps.max_bytes_per_response
        cap = min(cap, self.budget.remaining_bytes())

        self.budget.throttle(host)
        t0 = self._clock()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": accept},
            method="GET",
        )
        opener = self._opener_factory()

        body = bytearray()
        truncated = False
        try:
            with opener.open(req, timeout=self.budget.caps.request_timeout_seconds) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                ctype = resp.headers.get("Content-Type")
                while True:
                    # Read at most one byte past the cap: enough to know the body was
                    # oversized, without pulling a whole extra chunk we then discard.
                    want = min(_CHUNK, cap - len(body) + 1)
                    if want <= 0:
                        truncated = True
                        break
                    chunk = resp.read(want)
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > cap:
                        truncated = True
                        break
            elapsed = int((self._clock() - t0) * 1000)
            self.budget.record(host, len(body))
            if truncated:
                att = Attempt(url=url, host=host, source_id=source_id, purpose=purpose,
                              started_at=started, outcome="cap_exceeded", status=status,
                              bytes_downloaded=len(body), content_type=ctype,
                              elapsed_ms=elapsed, truncated=True,
                              reason_code="RESPONSE_BYTE_CAP",
                              error=f"body exceeded {cap} bytes and was abandoned")
            else:
                att = Attempt(url=url, host=host, source_id=source_id, purpose=purpose,
                              started_at=started, outcome="ok", status=status,
                              bytes_downloaded=len(body), content_type=ctype,
                              elapsed_ms=elapsed)
            att.body = bytes(body)  # type: ignore[attr-defined]
            return self.log.add(att)

        except urllib.error.HTTPError as exc:
            elapsed = int((self._clock() - t0) * 1000)
            # A refused redirect arrives here (3xx with no handler).
            detail = f"HTTP {exc.code} {exc.reason}"
            # `is not None`, not truthiness: an HTTPMessage with no headers is falsy.
            location = exc.headers.get("Location") if exc.headers is not None else None
            if location and 300 <= exc.code < 400:
                detail += f"; redirect to {location} not followed (target host must be granted separately)"
            self.budget.record(host, 0)
            att = Attempt(url=url, host=host, source_id=source_id, purpose=purpose,
                          started_at=started, outcome="http_error", status=exc.code,
                          elapsed_ms=elapsed, error=detail,
                          reason_code="REDIRECT_NOT_FOLLOWED" if location and 300 <= exc.code < 400 else None)
            att.body = b""  # type: ignore[attr-defined]
            return self.log.add(att)

        except Exception as exc:  # noqa: BLE001 -- probes must report, not crash
            elapsed = int((self._clock() - t0) * 1000)
            self.budget.record(host, 0)
            att = Attempt(url=url, host=host, source_id=source_id, purpose=purpose,
                          started_at=started, outcome="network_error",
                          elapsed_ms=elapsed, error=f"{type(exc).__name__}: {exc}")
            att.body = b""  # type: ignore[attr-defined]
            return self.log.add(att)
