"""Adapter for the CASCADE dataset (Guan, Sowndarya, Gallegos, St. John, Paton).

CASCADE is the most useful public source found for this project, because it is the
only one that ships both halves of a calibration record: experimental 13C shifts
and DFT values computed at a single fixed level of theory. Everything else
supplies measurements alone and leaves the calculation to you.

Citation. Guan, Y.; Sowndarya, S. V. S.; Gallegos, L. C.; St. John, P. C.;
Paton, R. S. Chem. Sci. 2021, DOI 10.1039/D1SC03343C.

Licence. The repository is MIT. The experimental shifts inside it are sampled
from NMRShiftDB, which is share-alike, so the repository licence does not settle
the question of the underlying data. Treat the corpus as carrying NMRShiftDB's
terms until someone with authority says otherwise. Share-alike constrains how a
derived database may be redistributed; it does not make the surrounding software
open source and does not by itself prevent commercial operation.

Two properties of this data decide how it may be used.

Selection. Exp5K is not a sample of chemistry. It is the subset of NMR8K that
already agreed with the DFT calculation, roughly five thousand of eight thousand
molecules, with residuals truncated near six ppm. A model calibrated on it will
produce intervals that are too narrow for molecules drawn from the wild, because
the molecules where the method fails were removed before calibration. This is
recorded on every corpus this module builds and should not be edited out.

Atom indexing. The experimental and DFT files agree on atom numbering only
through CASCADE's own curation. Joining the raw NMR8K assignments directly to
DFT8K by atom index produces residuals with a 99th percentile near 93 ppm and a
maximum past 200 ppm, which is misalignment rather than method error. So the
shifts are taken from Exp5K, and NMRShiftDB metadata is joined per molecule,
never per atom.
"""
import csv
import gzip
import io
import json
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/patonlab/cascade/master"
FILES = {
    "Exp5K.csv.gz": "data/Exp5K/Exp5K.csv.gz",
    "DFT8K.csv.gz": "data/DFT8K/DFT8K.csv.gz",
    "NMR8K.sdf.gz": "data/NMR8K/NMR8K.sdf.gz",
    "LICENSE": "LICENSE",
}

PROVENANCE = {
    "method": "mPW1PW91", "basis": "6-311+G(d,p)", "nucleus": "13C",
    "reference_compound": "unreported", "computed_kind": "shift",
    "source": "CASCADE (Chem. Sci. 2021, DOI 10.1039/D1SC03343C); experimental shifts from NMRShiftDB",
}

SELECTION_WARNING = (
    "Exp5K is the DFT-agreeing subset of NMR8K, not a sample of chemistry: molecules where the "
    "calculation failed were removed before calibration and residuals are truncated near 6 ppm. "
    "Intervals fitted here are optimistic for molecules drawn from the wild. Validate on a corpus "
    "that was never filtered by agreement before quoting coverage to a user."
)


def download(directory, base=BASE, files=None):
    """Fetch the CASCADE files into `directory`, skipping any already present."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fetched = {}
    for name, path in (files or FILES).items():
        target = directory / name
        if not target.exists():
            with urllib.request.urlopen(base + "/" + path, timeout=300) as response:
                target.write_bytes(response.read())
        fetched[name] = target
    return fetched


def _read_csv_gz(path):
    with gzip.open(path, "rt") as handle:
        return list(csv.DictReader(handle))


def _molecule_metadata(sdf_gz, directory):
    """Solvent and field per molecule, keyed by NMRShiftDB id.

    Molecule-level only. Atom-level joins across these files are not sound.
    """
    from .nmrshiftdb import load
    plain = Path(directory) / "NMR8K.sdf"
    if not plain.exists():
        with gzip.open(sdf_gz, "rb") as src:
            plain.write_bytes(src.read())
    meta = {}
    for record in load(plain):
        if record["nucleus"] != "13C" or record["unusable_reason"]:
            continue
        current = meta.get(record["native_id"])
        if current is None or (current["solvent"] is None and record["solvent"]):
            meta[record["native_id"]] = {"solvent": record["solvent"], "smiles": record["smiles"],
                                         "field_mhz": record["field_mhz"],
                                         "reference_compound": record["reference_compound"]}
    return meta


def load_records(directory, min_nuclei=3):
    """Return calibration-ready records pairing experimental and computed 13C shifts."""
    directory = Path(directory)
    observed = {(r["mol_id"], int(r["atom_index"])): float(r["Shift"])
                for r in _read_csv_gz(directory / "Exp5K.csv.gz")}
    computed = {(r["mol_id"], int(r["atom_index"])): float(r["Shift"])
                for r in _read_csv_gz(directory / "DFT8K.csv.gz") if r["atom_type"] == "6"}
    meta = _molecule_metadata(directory / "NMR8K.sdf.gz", directory)

    grouped = {}
    for key in sorted(set(observed) & set(computed)):
        grouped.setdefault(key[0], []).append(key)

    records = []
    for mol_id, keys in grouped.items():
        if len(keys) < min_nuclei:
            continue
        info = meta.get(mol_id, {})
        records.append({
            "id": "cascade:" + mol_id, "native_id": mol_id, "source": "cascade",
            "smiles": info.get("smiles"), "inchikey": None, "nucleus": "13C",
            "solvent": info.get("solvent"), "reference_compound": info.get("reference_compound"),
            "field_mhz": info.get("field_mhz"), "predicted": False, "unusable_reason": None,
            "licence": "MIT repository; experimental shifts derived from NMRShiftDB (CC BY-SA)",
            "nuclei": [{"atom_index": k[1], "element": "C",
                        "observed_shift_ppm": observed[k], "computed_shift_ppm": computed[k]}
                       for k in keys],
        })
    return records


def to_calibration_set(records, solvent=None):
    """Assemble one provenance slice into a calibration set.

    Pass `solvent` to restrict to a single recorded solvent. Passing None keeps
    every record including those whose solvent NMRShiftDB never recorded, which
    is most of them, and labels the slice accordingly.
    """
    selected = [r for r in records if solvent is None or r["solvent"] == solvent]
    provenance = dict(PROVENANCE, solvent=solvent or "mixed_or_unreported")
    return {
        "provenance": provenance,
        "records": [{"id": r["id"], "smiles": r["smiles"],
                     "nuclei": [{"index": n["atom_index"], "shielding_ppm": n["computed_shift_ppm"],
                                 "observed_shift_ppm": n["observed_shift_ppm"]} for n in r["nuclei"]]}
                    for r in selected],
        "selection_warning": SELECTION_WARNING,
    }


def summary(records):
    counts = {}
    for r in records:
        counts[r["solvent"]] = counts.get(r["solvent"], 0) + 1
    return {"molecules": len(records),
            "assigned_nuclei": sum(len(r["nuclei"]) for r in records),
            "solvents": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "selection_warning": SELECTION_WARNING,
            "licence": "MIT repository; experimental shifts derived from NMRShiftDB (CC BY-SA)"}
