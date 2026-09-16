"""Parser for the NMRShiftDB2 bulk SD file.

Licence note: NMRShiftDB2 content is share-alike. Read `sources.SOURCES` before
building a commercial corpus on it.

Two conventions in the file are not safe to assume, so both are detected per
molecule and recorded rather than hard-coded:

Atom index base. Assignments reference atoms by number. Whether that number is
zero or one based is inferred from the observed range against the molecule, and
a record whose base cannot be determined is marked ambiguous instead of guessed.

Hydrogen representation. A 1H assignment is only usable if the file carries
explicit hydrogens, otherwise the index addresses the heavy atom that bears the
proton and cannot be mapped onto the engine's per-atom shielding table. Such
records are marked and excluded from corpus assembly by default.
"""
import re

from .normalize import normalize_solvent, record_id

SPECTRUM_PROPERTY = re.compile(r"^Spectrum\s+([0-9]+[A-Za-z]+)\s*(\d*)$")
INDEXED_VALUE = re.compile(r"(\d+):\s*([^:]*?)(?=\s+\d+:|$)")


def parse_indexed(value):
    """Split '0:CDCl3 1:Unreported' into {0: 'CDCl3', 1: 'Unreported'}.

    NMRShiftDB records solvent, reference and field once per molecule, keyed by
    the spectrum number, because one structure can carry several spectra measured
    under different conditions. Reading the field as a single scalar would attach
    one spectrum's solvent to all of them.
    """
    text = str(value).strip()
    out = {}
    for match in INDEXED_VALUE.finditer(text):
        body = match.group(2).strip()
        out[int(match.group(1))] = body or None
    if not out and text:
        # Older exports write a single unprefixed value that covers every spectrum.
        out[None] = text
    return out


def _unreported(text):
    if text is None or str(text).strip().lower() in ("unreported", "unknown", ""):
        return None
    return str(text).strip()


def parse_peaks(value):
    """Parse 'shift;intensity;atom|shift;intensity;atom|' into triples.

    Tolerant by design: the multiplicity letter is sometimes fused to the
    intensity field, and trailing separators are common.
    """
    peaks = []
    for chunk in str(value).split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split(";")]
        while parts and not parts[-1]:      # trailing separators are common
            parts.pop()
        if len(parts) < 2:
            continue
        try:
            shift = float(parts[0])
        except ValueError:
            continue
        try:
            index = int(re.sub(r"[^0-9-]", "", parts[-1]))
        except ValueError:
            continue
        multiplicity = re.sub(r"[0-9.\s-]", "", parts[1]) or None if len(parts) > 2 else None
        peaks.append({"observed_shift_ppm": shift, "atom_index": index, "multiplicity": multiplicity})
    return peaks


def detect_index_base(indices, atom_count):
    """Return 0, 1, or None when the convention cannot be decided."""
    if not indices:
        return None
    low, high = min(indices), max(indices)
    zero_ok = low >= 0 and high < atom_count
    one_ok = low >= 1 and high <= atom_count
    if zero_ok and not one_ok:
        return 0
    if one_ok and not zero_ok:
        return 1
    if zero_ok and one_ok:
        return 0 if low == 0 else None
    return None


def iter_records(path, source="nmrshiftdb2"):
    """Yield canonical spectral records from an NMRShiftDB2 SD file."""
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")

    supplier = Chem.MultithreadedSDMolSupplier(str(path)) if hasattr(Chem, "MultithreadedSDMolSupplier") \
        else Chem.SDMolSupplier(str(path))
    for mol in supplier:
        if mol is None:
            continue
        props = mol.GetPropsAsDict(includePrivate=False, includeComputed=False)
        atom_count = mol.GetNumAtoms()
        has_explicit_h = any(a.GetAtomicNum() == 1 for a in mol.GetAtoms())
        try:
            smiles = Chem.MolToSmiles(mol)
            inchikey = Chem.MolToInchiKey(mol) or None
        except Exception:
            continue
        native = str(props.get("nmrshiftdb2 ID") or props.get("NMRSHIFTDB_ID") or mol.GetProp("_Name") or smiles)
        # NMRShiftDB carries predicted spectra alongside measured ones. They are not
        # flagged by "Spectrum Type"; they are flagged by the presence of a level of
        # theory or a prediction program for that spectrum number. Missing this is how
        # a calculated shift silently enters an experimental calibration set.
        models = parse_indexed(props.get("NMRModel", ""))
        basis_sets = parse_indexed(props.get("NMRBasisSet", ""))
        programs = parse_indexed(props.get("Program", ""))
        solvents = parse_indexed(props.get("Solvent", ""))
        standards = parse_indexed(props.get("NMRStandard", ""))
        fields = parse_indexed(props.get("Field Strength [MHz]", ""))
        temperatures = parse_indexed(props.get("Temperature [K]", ""))

        for name, value in props.items():
            match = SPECTRUM_PROPERTY.match(str(name))
            if not match:
                continue
            nucleus = match.group(1).upper()
            spectrum_number = int(match.group(2)) if match.group(2) else 0
            peaks = parse_peaks(value)
            if not peaks:
                continue
            base = detect_index_base([p["atom_index"] for p in peaks], atom_count)
            def for_spectrum(table):
                return table.get(spectrum_number, table.get(None))
            solvent = normalize_solvent(_unreported(for_spectrum(solvents)))
            field = _unreported(for_spectrum(fields))
            temperature = _unreported(for_spectrum(temperatures))
            standard = _unreported(for_spectrum(standards))
            model = _unreported(for_spectrum(models))
            basis = _unreported(for_spectrum(basis_sets))
            program = _unreported(for_spectrum(programs))
            calculated = bool(model or basis or program)
            yield {
                "_atom_symbols": [a.GetSymbol() for a in mol.GetAtoms()],
                "_has_explicit_h": has_explicit_h,
                "spectrum_number": spectrum_number,
                "id": record_id(source, native, nucleus, solvent),
                "source": source, "native_id": native, "smiles": smiles, "inchikey": inchikey,
                "nucleus": nucleus, "solvent": solvent,
                "reference_compound": standard,
                "field_mhz": _as_float(field),
                "temperature_k": _as_float(temperature),
                "predicted": calculated or "predicted" in str(props.get("Spectrum Type", "")).lower(),
                "record_status": "calculated" if calculated else "measured",
                "computed_model": model, "computed_basis": basis, "computed_program": program,
                "atom_count": atom_count, "index_base_detected": base,
                "unusable_reason": None,
                "nuclei": peaks,
                "licence": "CC BY-SA (NMRShiftDB2)",
            }


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_index_bases(records, corpus_fallback=True):
    """Settle the atom index convention, then assign elements and usability.

    A single spectrum whose indices happen to fit both conventions is ambiguous
    on its own evidence. Across a whole file the convention is not in doubt, so
    the majority of the records that ARE unambiguous decides the rest. That is
    inference from the corpus, not a guess, and every record records which of the
    two it got through `index_base_source`.
    """
    decided = [r["index_base_detected"] for r in records if r["index_base_detected"] is not None]
    majority = None
    if corpus_fallback and decided:
        majority = max(set(decided), key=decided.count)
        if decided.count(majority) < 0.9 * len(decided):
            majority = None       # the file is not internally consistent; do not extrapolate

    for r in records:
        symbols = r.pop("_atom_symbols", [])
        explicit_h = r.pop("_has_explicit_h", True)
        base = r["index_base_detected"]
        r["index_base_source"] = "detected" if base is not None else (
            "corpus_majority" if majority is not None else None)
        if base is None:
            base = majority
        if base is None:
            r["unusable_reason"] = "ambiguous_atom_index_base"
            r["nuclei"] = []
            continue
        r["index_base_applied"] = base
        kept = []
        for p in r["nuclei"]:
            idx = p["atom_index"] - base
            if not 0 <= idx < len(symbols):
                continue
            p["atom_index"] = idx
            p["element"] = symbols[idx]
            kept.append(p)
        r["nuclei"] = kept
        if r["nucleus"] == "1H" and not explicit_h:
            r["unusable_reason"] = "implicit_hydrogens_cannot_be_indexed"
        elif not kept:
            r["unusable_reason"] = "no_assignment_within_molecule"
    return records


def load(path, corpus_fallback=True, **kw):
    return resolve_index_bases(list(iter_records(path, **kw)), corpus_fallback=corpus_fallback)
