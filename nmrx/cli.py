"""Command line entry point: ``python -m nmrx <command>``.

Commands are read-only except ``probe``, which is the only one that touches the network --
and it refuses any host the access policy has not granted.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .model.calibration import rule_catalogue
from .reports.coverage import render_text as render_coverage
from .reports.coverage import source_coverage
from .sources.policy import load_policy
from .sources.registry import load_registry


def _cmd_registry(args) -> int:
    registry = load_registry()
    if args.source_id:
        source = registry.get(args.source_id)
        if source is None:
            print(f"no source with id {args.source_id!r}", file=sys.stderr)
            print("known ids: " + ", ".join(registry.ids()), file=sys.stderr)
            return 1
        print(json.dumps(source.raw, indent=2))
        return 0
    if args.json:
        print(json.dumps(registry.summary(), indent=2))
        return 0

    print(f"{len(registry)} sources\n")
    header = f"{'id':<20} {'tier':<16} {'status':<16} {'rights':<18} NMR"
    print(header)
    print("-" * len(header))
    for s in sorted(registry, key=lambda x: (x.tier, x.id)):
        nmr = ""
        if s.has_nmr:
            nmr = f"assignments={s.assignments} conditions={s.conditions}"
        print(f"{s.id:<20} {s.tier:<16} {s.status:<16} {s.rights_status:<18} {nmr}")
    return 0


def _cmd_policy(args) -> int:
    policy = load_policy()
    print(f"policy version {policy.policy_version}  (pilot status: {policy.pilot_status})\n")
    print("GRANTED hosts -- NMRx may call these, if the environment also allows them:")
    for g in policy.granted_hosts():
        print(f"  {g.host:<34} {g.source_id:<12} {g.purpose}")
        if g.hostname_caution:
            print(f"      ! {g.hostname_caution}")
    print("\nASSESSED but NOT granted -- needs an explicit decision first:")
    for c in policy.candidate_hosts():
        print(f"  {c['host']:<34} {c['source_id']:<12} {c['purpose']}")
    print("\nPROHIBITED -- never add these:")
    for p in policy.prohibited_hosts():
        print(f"  {p['host']:<34} {p['reason']}")
    caps = policy.caps
    print(f"\nCaps ({caps.provenance}):")
    print(f"  max {caps.max_requests_per_job} requests per job")
    print(f"  max {caps.max_bytes_per_response:,} bytes per response")
    print(f"  max {caps.max_bytes_per_job:,} bytes per job")
    print(f"  min {caps.min_seconds_between_requests_per_host}s between requests to one host")
    return 0


def _cmd_probe(args) -> int:
    from .sources.probe import load_plan, render_text, run, write_report

    steps = load_plan()
    if args.dry_run:
        print(f"{len(steps)} steps planned. Nothing was sent (--dry-run).\n")
        for s in steps:
            print(f"  {s.source_id:<12} {s.url}")
        return 0

    report = run(steps)
    print(render_text(report))
    if args.write:
        path = write_report(report)
        print(f"\nwritten: {path}")
    return 0


def _cmd_coverage(args) -> int:
    registry = load_registry()
    coverage = source_coverage(registry)
    if args.json:
        print(json.dumps(coverage, indent=2))
        return 0
    print(render_coverage(coverage))
    return 0


def _cmd_rules(args) -> int:
    print("Strict NMR calibration gate -- a record must pass every rule:\n")
    for rule in rule_catalogue():
        print(f"  {rule['rule_id']}  {rule['statement']}")
        print(f"            rejects with: {rule['rejects_with']}")
    print("\nA record that fails these is still kept for discovery, clearly labelled,")
    print("unless its atom mapping is actually invalid (CAL-007).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nmrx",
        description="NMRx source registry, access policy and NMR data layer.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("registry", help="list sources, or show one in full")
    p.add_argument("source_id", nargs="?", help="show this source's full entry")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    p.set_defaults(func=_cmd_registry)

    p = sub.add_parser("policy", help="show which hosts NMRx may actually call")
    p.set_defaults(func=_cmd_policy)

    p = sub.add_parser("probe", help="run the bounded pilot connectivity probe")
    p.add_argument("--dry-run", action="store_true", help="print the plan without sending anything")
    p.add_argument("--write", action="store_true", help="save the report under nmrx/data/probes/")
    p.set_defaults(func=_cmd_probe)

    p = sub.add_parser("coverage", help="source coverage and NMR completeness")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_coverage)

    p = sub.add_parser("rules", help="explain the calibration eligibility rules")
    p.set_defaults(func=_cmd_rules)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
