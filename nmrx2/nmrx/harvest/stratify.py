"""Partition harvested records into calibratable corpora and report what survives.

This is the module that answers the question 'we harvested forty thousand
spectra, how many can we actually calibrate'. The answer is usually far smaller
than the harvest, because the coverage guarantee only holds within one
exchangeable population. A corpus mixing solvents, references or nuclei is not
one population, so the harvest must be sliced before it is counted, and most
slices fall below the size the conformal quantile requires.
"""
import math

from ..calibration import minimum_calibration_size
from .normalize import slice_key


def required_total(alpha=0.05, train_fraction=0.5):
    """Molecules a corpus needs so the calibration split clears the quantile."""
    return int(math.ceil(minimum_calibration_size(alpha) / (1 - train_fraction))) + 1


def stratify(records, alpha=0.05, train_fraction=0.5, field_tolerance_mhz=None):
    """Group records into provenance slices and mark each usable or not.

    `field_tolerance_mhz` buckets spectrometer field, which is not part of the
    exchangeability argument in the same way solvent is, but correlates with
    instrument era and referencing practice. Leave it None to ignore field.
    """
    need = required_total(alpha, train_fraction)
    groups = {}
    for r in records:
        nucleus, solvent, reference, field = slice_key(r)
        if field_tolerance_mhz and field:
            field = int(round(field / field_tolerance_mhz) * field_tolerance_mhz)
        else:
            field = None
        groups.setdefault((nucleus, solvent, reference, field), []).append(r)

    slices = []
    for key, members in groups.items():
        molecules = len({m.get("inchikey") or m.get("smiles") for m in members})
        slices.append({
            "nucleus": key[0], "solvent": key[1], "reference_compound": key[2], "field_mhz": key[3],
            "records": len(members), "distinct_molecules": molecules,
            "assigned_nuclei": sum(len(m["nuclei"]) for m in members),
            "usable": molecules >= need,
            "shortfall": max(0, need - molecules),
        })
    slices.sort(key=lambda s: -s["distinct_molecules"])
    usable = [s for s in slices if s["usable"]]
    return {
        "alpha": alpha, "train_fraction": train_fraction,
        "required_molecules_per_corpus": need,
        "total_records": len(records),
        "total_slices": len(slices),
        "usable_slices": len(usable),
        "molecules_in_usable_slices": sum(s["distinct_molecules"] for s in usable),
        "molecules_stranded_below_threshold": sum(s["distinct_molecules"] for s in slices if not s["usable"]),
        "slices": slices,
        "note": "Each usable slice is a separate corpus with its own scaling and its own quantile. "
                "Slices cannot be merged to reach the threshold: merging different solvents or references "
                "breaks the exchangeability the coverage guarantee depends on.",
    }


def format_report(summary, limit=25):
    lines = [
        "alpha %.2f, train fraction %.2f, %d molecules required per corpus"
        % (summary["alpha"], summary["train_fraction"], summary["required_molecules_per_corpus"]),
        "%d records in %d slices; %d slices usable; %d molecules stranded below threshold"
        % (summary["total_records"], summary["total_slices"], summary["usable_slices"],
           summary["molecules_stranded_below_threshold"]),
        "",
        "Nucleus  Solvent          Reference   Molecules  Nuclei   Status",
    ]
    for s in summary["slices"][:limit]:
        lines.append("%-8s %-16s %-11s %9d %7d   %s" % (
            s["nucleus"] or "?", str(s["solvent"] or "unknown")[:16], str(s["reference_compound"] or "unknown")[:11],
            s["distinct_molecules"], s["assigned_nuclei"],
            "usable" if s["usable"] else "short by %d" % s["shortfall"]))
    if len(summary["slices"]) > limit:
        lines.append("... %d further slices" % (len(summary["slices"]) - limit))
    return "\n".join(lines)
