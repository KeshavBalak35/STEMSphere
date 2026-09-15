"""Canonical spectral records, quality filters and assembly into a calibration set.

A harvested record is half of what the calibration layer needs. Public databases
carry the measured shift. None of them carry the computed shielding at your level
of theory, because that depends on a calculation nobody has run yet. So the
pipeline is:

    harvest  ->  spectral records (observed only)
             ->  quantum NMR job per molecule at one fixed level
             ->  calibration set (observed paired with computed)

`to_calibration_set` refuses to assemble a corpus with a shielding missing,
rather than dropping the nucleus and quietly changing what was calibrated.
"""
import hashlib
import re

# Plausible shift windows. Values outside these are transcription or unit errors
# far more often than they are real chemistry, and one of them can widen every
# interval in a corpus.
NUCLEUS_RANGES = {"1H": (-6.0, 22.0), "13C": (-25.0, 250.0), "19F": (-300.0, 100.0),
                  "31P": (-250.0, 300.0), "15N": (-400.0, 1000.0)}

NUCLEUS_ELEMENT = {"1H": "H", "13C": "C", "19F": "F", "31P": "P", "15N": "N"}

_SOLVENT_ALIASES = {
    "cdcl3": "CDCl3", "chloroform-d": "CDCl3", "chloroform-d1": "CDCl3", "cdcl-3": "CDCl3",
    "dmso": "DMSO-d6", "dmso-d6": "DMSO-d6", "(cd3)2so": "DMSO-d6", "dimethylsulphoxide-d6": "DMSO-d6",
    "d2o": "D2O", "water-d2": "D2O", "deuteriumoxide": "D2O",
    "methanol-d4": "CD3OD", "cd3od": "CD3OD", "meod": "CD3OD",
    "benzene-d6": "C6D6", "c6d6": "C6D6",
    "acetone-d6": "acetone-d6", "cd3cocd3": "acetone-d6",
    "acetonitrile-d3": "CD3CN", "cd3cn": "CD3CN",
    "gas": "gas phase", "gas phase": "gas phase", "none": None, "unknown": None, "": None,
}


def normalize_solvent(raw):
    """Map a free-text solvent string onto a canonical name, or None if unknown.

    Unknown is returned as None rather than guessed. Solvent is part of the
    provenance key, so a wrong guess silently merges two populations that are not
    exchangeable and invalidates the coverage guarantee.
    """
    if raw is None:
        return None
    key = re.sub(r"[\s_]+", "", str(raw).strip().lower())
    if key in _SOLVENT_ALIASES:
        return _SOLVENT_ALIASES[key]
    spaced = str(raw).strip().lower()
    return _SOLVENT_ALIASES.get(spaced, str(raw).strip() or None)


def record_id(source, native_id, nucleus, solvent):
    blob = "|".join(str(x) for x in (source, native_id, nucleus, solvent))
    return source + ":" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def quality_filter(records, nucleus=None, require_solvent=True, require_reference=False,
                   min_nuclei=1, drop_predicted=True):
    """Filter harvested records, returning kept records and a reason tally."""
    kept, rejected = [], {}

    def drop(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    for r in records:
        if nucleus and r.get("nucleus") != nucleus:
            drop("wrong_nucleus"); continue
        if drop_predicted and r.get("predicted"):
            drop("predicted_not_measured"); continue
        if require_solvent and not r.get("solvent"):
            drop("missing_solvent"); continue
        if require_reference and not r.get("reference_compound"):
            drop("missing_reference"); continue
        peaks = r.get("nuclei") or []
        element = NUCLEUS_ELEMENT.get(r.get("nucleus"))
        low, high = NUCLEUS_RANGES.get(r.get("nucleus"), (-1e9, 1e9))
        clean = []
        for p in peaks:
            if p.get("atom_index") is None:
                continue
            if element and p.get("element") and p["element"] != element:
                continue
            shift = p.get("observed_shift_ppm")
            if shift is None or not (low <= shift <= high):
                continue
            clean.append(p)
        if len(clean) < min_nuclei:
            drop("too_few_usable_assignments"); continue
        seen = {p["atom_index"] for p in clean}
        if len(seen) != len(clean):
            drop("duplicate_atom_assignment"); continue
        kept.append(dict(r, nuclei=clean))
    return kept, rejected


def deduplicate(records, prefer="most_nuclei"):
    """Collapse records describing the same molecule in the same provenance slice.

    Duplicates break exchangeability by weighting one molecule twice in the
    calibration scores, which narrows intervals without justification.
    """
    best = {}
    for r in records:
        key = (r.get("inchikey") or r.get("smiles"), r.get("nucleus"),
               r.get("solvent"), r.get("reference_compound"))
        current = best.get(key)
        if current is None:
            best[key] = r
        elif prefer == "most_nuclei" and len(r["nuclei"]) > len(current["nuclei"]):
            best[key] = r
    return list(best.values())


def slice_key(record):
    return (record.get("nucleus"), record.get("solvent"),
            record.get("reference_compound"), record.get("field_mhz"))


def pending_quantum_jobs(records, method="B3LYP", basis="def2-svp", conformers=5, seed=42):
    """Quantum NMR payloads needed to complete these records into a corpus.

    One job per distinct structure. This is the expensive half of the pipeline and
    the reason 'harvest everything' does not translate into 'calibrate everything'.
    """
    jobs, seen = [], set()
    for r in records:
        smiles = r.get("smiles")
        if not smiles or smiles in seen:
            continue
        seen.add(smiles)
        jobs.append({"smiles": smiles, "task": "nmr", "method": method, "basis": basis,
                     "conformers": conformers, "seed": seed, "optimize": True,
                     "_record_ids": [x["id"] for x in records if x.get("smiles") == smiles]})
    return jobs


def to_calibration_set(records, shieldings, provenance, strict=True):
    """Pair observed shifts with computed shieldings into a calibration set.

    `shieldings` maps a record id, or the record's smiles, to the per-atom
    isotropic shielding list returned by the quantum engine. Atom indices in the
    record must address that list directly, on the same zero-based convention the
    engine reports.
    """
    out, missing = [], []
    for r in records:
        table = shieldings.get(r["id"]) or shieldings.get(r.get("smiles"))
        if table is None:
            missing.append(r["id"]); continue
        nuclei = []
        for p in r["nuclei"]:
            i = p["atom_index"]
            if not 0 <= i < len(table):
                missing.append(r["id"] + " atom " + str(i)); break
            nuclei.append({"index": i, "shielding_ppm": float(table[i]),
                           "observed_shift_ppm": float(p["observed_shift_ppm"])})
        else:
            out.append({"id": r["id"], "smiles": r.get("smiles"), "nuclei": nuclei})
    if missing and strict:
        raise ValueError("Computed shieldings missing for %d entries; first: %s. "
                         "Run the quantum jobs from pending_quantum_jobs before assembling a corpus."
                         % (len(missing), missing[0]))
    return {"provenance": provenance, "records": out}
