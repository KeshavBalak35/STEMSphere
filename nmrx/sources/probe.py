"""The pilot connectivity probe.

Runs a small, bounded set of requests through the policy gate and the byte-capped client,
then writes a report saying exactly what was attempted, what came back, and how many bytes
moved. It is deliberately honest about three different kinds of "no":

``policy_denied``
    NMRx itself refused -- host not granted, prohibited, or credentials required. No socket
    was opened, so this says nothing about whether the host is reachable.
``network_error`` with a proxy 403
    the *environment's* egress policy refused the CONNECT. The host is not on the cloud
    environment's Allowed-domains list. No project setting can fix this.
``http_error`` / ``ok``
    we actually reached the service.

Being blocked at the environment layer is reported once per host and not retried; repeating
an unchanged blocked probe produces no new information.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .http import Attempt, BoundedHttpClient, RequestLog
from .policy import AccessPolicy, load_policy

PROBE_PLAN_PATH = Path(__file__).resolve().parent.parent / "data" / "pilot_probe_plan.json"
PROBE_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "probes"

#: Substrings that identify an egress-policy refusal rather than a service problem.
_EGRESS_MARKERS = (
    "CONNECT tunnel failed",
    "Tunnel connection failed",
    "response 403",
    "403 Forbidden",
    "ProxyError",
)


@dataclass
class ProbeStep:
    source_id: str
    purpose: str
    url: str
    expect: str = ""
    note: str = ""


def load_plan(path: Path | str = PROBE_PLAN_PATH) -> List[ProbeStep]:
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    return [ProbeStep(**s) for s in doc["steps"]]


def classify(attempt: Attempt) -> str:
    """Turn a raw attempt into the blocker class a human report needs."""
    if attempt.outcome == "ok":
        return "reachable"
    if attempt.outcome == "cap_exceeded":
        return "reachable_but_over_cap"
    if attempt.outcome == "policy_denied":
        return "refused_by_project_policy"
    if attempt.outcome == "http_error":
        return "reached_service_http_error"
    err = attempt.error or ""
    if any(marker in err for marker in _EGRESS_MARKERS):
        return "blocked_by_environment_network_policy"
    return "network_failure"


def run(
    steps: Sequence[ProbeStep],
    policy: Optional[AccessPolicy] = None,
    client: Optional[BoundedHttpClient] = None,
    stop_host_after_block: bool = True,
) -> dict:
    """Execute the probe plan once.

    ``stop_host_after_block`` honours the standing instruction not to repeat an unchanged
    blocked probe: once a host is refused by the environment, its remaining steps are
    recorded as skipped rather than retried.
    """
    policy = policy or load_policy()
    client = client or BoundedHttpClient(policy)

    blocked_hosts: Dict[str, str] = {}
    results: List[dict] = []

    for step in steps:
        try:
            host = policy.host_of(step.url)
        except Exception:
            host = "(unparsed)"

        if stop_host_after_block and host in blocked_hosts:
            results.append({
                "source_id": step.source_id,
                "purpose": step.purpose,
                "url": step.url,
                "host": host,
                "classification": "skipped_host_already_blocked",
                "detail": blocked_hosts[host],
                "bytes_downloaded": 0,
                "status": None,
            })
            continue

        attempt = client.get(step.url, source_id=step.source_id, purpose=step.purpose)
        klass = classify(attempt)
        if klass == "blocked_by_environment_network_policy":
            blocked_hosts[host] = attempt.error or ""
        results.append({
            "source_id": step.source_id,
            "purpose": step.purpose,
            "url": step.url,
            "host": host,
            "classification": klass,
            "status": attempt.status,
            "bytes_downloaded": attempt.bytes_downloaded,
            "elapsed_ms": attempt.elapsed_ms,
            "error": attempt.error,
            "reason_code": attempt.reason_code,
            "expect": step.expect,
            "note": step.note,
        })

    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy_version": policy.policy_version,
        "caps": {
            "max_requests_per_job": policy.caps.max_requests_per_job,
            "max_bytes_per_response": policy.caps.max_bytes_per_response,
            "max_bytes_per_job": policy.caps.max_bytes_per_job,
            "caps_provenance": policy.caps.provenance,
        },
        "steps_planned": len(steps),
        "steps_executed": sum(1 for r in results
                              if r["classification"] != "skipped_host_already_blocked"),
        "total_bytes_downloaded": sum(r["bytes_downloaded"] for r in results),
        "classification_counts": _counts(results),
        "blocked_hosts": sorted(blocked_hosts),
        "results": results,
        "request_log": client.log.to_dict(),
    }


def _counts(results: Sequence[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in results:
        out[r["classification"]] = out.get(r["classification"], 0) + 1
    return out


def write_report(report: dict, directory: Path | str = PROBE_OUTPUT_DIR,
                 name: Optional[str] = None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = name or f"pilot_probe_{report['run_at'][:10]}.json"
    path = directory / name
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    return path


def render_text(report: dict) -> str:
    lines = [
        f"Pilot probe {report['run_at']} (policy {report['policy_version']})",
        f"  planned {report['steps_planned']}, executed {report['steps_executed']}, "
        f"bytes downloaded {report['total_bytes_downloaded']}",
    ]
    for k, v in sorted(report["classification_counts"].items()):
        lines.append(f"  {k}: {v}")
    if report["blocked_hosts"]:
        lines.append("  blocked by environment network policy:")
        for h in report["blocked_hosts"]:
            lines.append(f"    - {h}")
    return "\n".join(lines)
