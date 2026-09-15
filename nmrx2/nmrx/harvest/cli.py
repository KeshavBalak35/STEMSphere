"""Command line entry point for the harvest pipeline.

    python -m nmrx.harvest.cli sources
    python -m nmrx.harvest.cli ingest nmrshiftdb2.sdf --nucleus 13C --out records.json
    python -m nmrx.harvest.cli jobs records.json --out jobs.json --basis def2-tzvp
"""
import argparse
import json
import sys

from . import nmrshiftdb, normalize, sources
from .stratify import format_report, stratify

PARSERS = {"nmrshiftdb2": nmrshiftdb.load}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nmrx.harvest", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list data sources with licence and bulk-access status")

    ingest = sub.add_parser("ingest", help="parse a bulk file into filtered, stratified records")
    ingest.add_argument("path")
    ingest.add_argument("--source", default="nmrshiftdb2", choices=sorted(PARSERS))
    ingest.add_argument("--nucleus", default=None, help="keep only this nucleus, e.g. 13C")
    ingest.add_argument("--alpha", type=float, default=0.05)
    ingest.add_argument("--train-fraction", type=float, default=0.5)
    ingest.add_argument("--min-nuclei", type=int, default=3)
    ingest.add_argument("--require-reference", action="store_true",
                        help="drop records with no recorded reference compound")
    ingest.add_argument("--out", default=None, help="write kept records as JSON")

    jobs = sub.add_parser("jobs", help="emit the quantum NMR payloads a corpus still needs")
    jobs.add_argument("path")
    jobs.add_argument("--method", default="B3LYP")
    jobs.add_argument("--basis", default="def2-svp")
    jobs.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    if args.command == "sources":
        print(sources.report())
        return 0

    if args.command == "ingest":
        raw = PARSERS[args.source](args.path)
        blocked = [r for r in raw if r.get("unusable_reason")]
        usable_raw = [r for r in raw if not r.get("unusable_reason")]
        kept, rejected = normalize.quality_filter(
            usable_raw, nucleus=args.nucleus, min_nuclei=args.min_nuclei,
            require_reference=args.require_reference)
        kept = normalize.deduplicate(kept)
        summary = stratify(kept, alpha=args.alpha, train_fraction=args.train_fraction)

        print("parsed %d records from %s" % (len(raw), args.path))
        if blocked:
            reasons = {}
            for r in blocked:
                reasons[r["unusable_reason"]] = reasons.get(r["unusable_reason"], 0) + 1
            print("unusable at parse time: " + ", ".join("%s=%d" % kv for kv in sorted(reasons.items())))
        if rejected:
            print("filtered out: " + ", ".join("%s=%d" % kv for kv in sorted(rejected.items())))
        print("kept %d records after filtering and deduplication\n" % len(kept))
        print(format_report(summary))
        print("\n" + summary["note"])
        if args.out:
            with open(args.out, "w") as fh:
                json.dump({"records": kept, "stratification": summary}, fh)
            print("\nwrote %s" % args.out)
        return 0

    if args.command == "jobs":
        with open(args.path) as fh:
            payload = json.load(fh)
        records = payload["records"] if isinstance(payload, dict) else payload
        queue = normalize.pending_quantum_jobs(records, method=args.method, basis=args.basis)
        print("%d distinct structures need a quantum NMR job at %s/%s"
              % (len(queue), args.method, args.basis))
        print("No public database supplies the computed shielding. This is the expensive half.")
        if args.out:
            with open(args.out, "w") as fh:
                json.dump(queue, fh)
            print("wrote %s" % args.out)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
