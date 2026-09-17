"""Access policy gate for every outbound NMRx request.

Two separate gates must both be open before NMRx may contact a host:

1. **Project policy** (this module, driven by ``nmrx/data/access_policy.json``) -- which
   hosts this project has decided it may call, and the request/byte caps for a job.
2. **Environment network policy** -- the Claude Code cloud environment's own
   "Allowed domains" list. This module cannot open that gate; a host denied there
   fails at CONNECT with HTTP 403 no matter what this file says.

Being listed in the 50-entry source registry grants nothing. The registry is a research
directory. Only ``access_policy.json`` grants.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlsplit

POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "access_policy.json"


class PolicyDenied(Exception):
    """Raised when a request is refused before any socket is opened.

    ``reason_code`` is stable and safe to assert on in tests and to report to the user.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"[{reason_code}] {message}")
        self.reason_code = reason_code
        self.message = message


@dataclass
class Caps:
    max_requests_per_job: int
    max_bytes_per_response: int
    max_bytes_per_job: int
    min_seconds_between_requests_per_host: float
    request_timeout_seconds: int
    follow_redirects_to_new_hosts: bool
    provenance: str

    @classmethod
    def from_dict(cls, d: dict) -> "Caps":
        return cls(
            max_requests_per_job=int(d["max_requests_per_job"]),
            max_bytes_per_response=int(d["max_bytes_per_response"]),
            max_bytes_per_job=int(d["max_bytes_per_job"]),
            min_seconds_between_requests_per_host=float(d["min_seconds_between_requests_per_host"]),
            request_timeout_seconds=int(d["request_timeout_seconds"]),
            follow_redirects_to_new_hosts=bool(d["follow_redirects_to_new_hosts"]),
            provenance=str(d.get("_provenance", "unknown")),
        )


@dataclass
class GrantedHost:
    host: str
    source_id: str
    purpose: str
    documented_rate_limit: Optional[str] = None
    hostname_caution: Optional[str] = None


@dataclass
class JobBudget:
    """Per-job counters. A job is one harvest/probe run, not the process lifetime."""

    caps: Caps
    requests_made: int = 0
    bytes_downloaded: int = 0
    _last_request_at: Dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remaining_requests(self) -> int:
        return max(0, self.caps.max_requests_per_job - self.requests_made)

    def remaining_bytes(self) -> int:
        return max(0, self.caps.max_bytes_per_job - self.bytes_downloaded)

    def check_before(self, host: str) -> None:
        with self._lock:
            if self.requests_made >= self.caps.max_requests_per_job:
                raise PolicyDenied(
                    "JOB_REQUEST_CAP",
                    f"job request cap reached ({self.caps.max_requests_per_job}); "
                    "raise max_requests_per_job in access_policy.json only on an explicit instruction",
                )
            if self.bytes_downloaded >= self.caps.max_bytes_per_job:
                raise PolicyDenied(
                    "JOB_BYTE_CAP",
                    f"job byte cap reached ({self.caps.max_bytes_per_job} bytes)",
                )

    def throttle(self, host: str, sleep=time.sleep, now=time.monotonic) -> float:
        """Block until this host's documented minimum spacing has elapsed. Returns seconds waited."""
        gap = self.caps.min_seconds_between_requests_per_host
        if gap <= 0:
            return 0.0
        with self._lock:
            last = self._last_request_at.get(host)
            current = now()
            wait = 0.0 if last is None else max(0.0, gap - (current - last))
            self._last_request_at[host] = current + wait
        if wait > 0:
            sleep(wait)
        return wait

    def record(self, host: str, n_bytes: int) -> None:
        with self._lock:
            self.requests_made += 1
            self.bytes_downloaded += n_bytes

    def check_response_size(self, n_bytes: int) -> None:
        if n_bytes > self.caps.max_bytes_per_response:
            raise PolicyDenied(
                "RESPONSE_BYTE_CAP",
                f"response of {n_bytes} bytes exceeds max_bytes_per_response "
                f"({self.caps.max_bytes_per_response})",
            )


class AccessPolicy:
    """Loads access_policy.json and answers 'may NMRx call this URL?'."""

    def __init__(self, data: dict) -> None:
        self._data = data
        pilot = data["pilot"]
        self.policy_version: str = data["policy_version"]
        self.pilot_status: str = pilot["status"]
        self.caps = Caps.from_dict(pilot["caps"])
        self._granted: Dict[str, GrantedHost] = {}
        for h in pilot["allowed_hosts"]:
            self._granted[h["host"].lower()] = GrantedHost(
                host=h["host"],
                source_id=h["source_id"],
                purpose=h["purpose"],
                documented_rate_limit=h.get("documented_rate_limit"),
                hostname_caution=h.get("hostname_caution"),
            )
        self._prohibited: Dict[str, dict] = {
            p["host"].lower(): p for p in data.get("prohibited_hosts", [])
        }
        self._candidates: Dict[str, dict] = {
            c["host"].lower(): c for c in data.get("candidate_expansion", {}).get("hosts", [])
        }
        self._credentialed: Dict[str, dict] = {
            c["source_id"]: c for c in data.get("credential_or_licence_required", [])
        }

    @classmethod
    def load(cls, path: Path | str = POLICY_PATH) -> "AccessPolicy":
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh))

    # -- introspection -------------------------------------------------------

    def granted_hosts(self) -> List[GrantedHost]:
        return sorted(self._granted.values(), key=lambda g: g.host)

    def candidate_hosts(self) -> List[dict]:
        return sorted(self._candidates.values(), key=lambda c: c["host"])

    def prohibited_hosts(self) -> List[dict]:
        return sorted(self._prohibited.values(), key=lambda p: p["host"])

    def credential_blocker(self, source_id: str) -> Optional[str]:
        entry = self._credentialed.get(source_id)
        return entry["blocker"] if entry else None

    def new_budget(self) -> JobBudget:
        return JobBudget(caps=self.caps)

    # -- the gate ------------------------------------------------------------

    def host_of(self, url: str) -> str:
        """Normalise ``url`` to the hostname the request would actually reach.

        Four things are refused here rather than at match time, because each one lets a
        string that *looks* like a granted host reach somewhere else:

        * a scheme other than https;
        * embedded credentials -- NMRx has no authenticated grant, and a userinfo segment
          would otherwise be written verbatim into the request log;
        * a port other than 443 -- a granted host on another port is a different service;
        * a trailing dot (``host.``) -- the DNS root form resolves the same but would not
          match a prohibition entry by string comparison.
        """
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise PolicyDenied(
                "SCHEME_NOT_HTTPS",
                f"only https is permitted, got {parts.scheme or '(none)'} in {url!r}",
            )
        if not parts.hostname:
            raise PolicyDenied("NO_HOST", f"could not parse a hostname from {url!r}")
        if parts.username is not None or parts.password is not None:
            raise PolicyDenied(
                "CREDENTIALS_IN_URL",
                "credentials embedded in a URL are refused: no granted source is "
                "authenticated, and the userinfo segment would be recorded in the request log",
            )
        try:
            port = parts.port
        except ValueError:
            raise PolicyDenied("BAD_PORT", f"unparseable port in {url!r}") from None
        if port not in (None, 443):
            raise PolicyDenied(
                "PORT_NOT_443",
                f"port {port} is not 443; a granted host reached on another port is a "
                "different service and is not covered by the grant",
            )
        # Strip the DNS root dot so "host." cannot dodge an exact prohibition match.
        return parts.hostname.lower().rstrip(".")

    def authorize(self, url: str, *, source_id: Optional[str] = None) -> GrantedHost:
        """Return the grant for ``url`` or raise :class:`PolicyDenied`.

        Matching is exact on the hostname. ``www.bindingdb.org`` being granted does NOT
        grant ``bindingdb.org`` or ``ww.bindingdb.org`` -- the map flags those as distinct
        hosts and a wildcard here would silently widen the pilot.
        """
        host = self.host_of(url)

        if host in self._prohibited:
            p = self._prohibited[host]
            raise PolicyDenied(
                "HOST_PROHIBITED",
                f"{host} is on the prohibited list: {p['reason']}",
            )

        if source_id:
            blocker = self.credential_blocker(source_id)
            if blocker:
                raise PolicyDenied(
                    "CREDENTIAL_REQUIRED",
                    f"source {source_id!r} needs {blocker} before any request",
                )

        grant = self._granted.get(host)
        if grant is None:
            if host in self._candidates:
                c = self._candidates[host]
                raise PolicyDenied(
                    "HOST_CANDIDATE_NOT_GRANTED",
                    f"{host} is an assessed expansion candidate for source "
                    f"{c['source_id']!r} but has not been granted; it needs an explicit "
                    "user decision and an environment Allowed-domains change",
                )
            raise PolicyDenied(
                "HOST_NOT_GRANTED",
                f"{host} is not in access_policy.json. Being in the source registry is not "
                "permission. Add it deliberately, with the smallest exact operation and an "
                "estimated byte count, before calling it.",
            )

        if source_id and grant.source_id != source_id and grant.source_id != "ebi_shared":
            raise PolicyDenied(
                "SOURCE_HOST_MISMATCH",
                f"{host} is granted for source {grant.source_id!r}, not {source_id!r}",
            )

        return grant


def load_policy(path: Path | str = POLICY_PATH) -> AccessPolicy:
    return AccessPolicy.load(path)
