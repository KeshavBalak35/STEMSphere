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
        solvent = normalize_solvent(props.get("Solvent"))
        field = props.get("Field Strength [MHz]")
        temperature = props.get("Temperature [K]")

        for name, value in props.items():
            match = SPECTRUM_PROPERTY.match(str(name))
            if not match:
                continue
            nucleus = match.group(1).upper().replace("H", "H")
            peaks = parse_peaks(value)
            if not peaks:
                continue
            base = detect_index_base([p["atom_index"] for p in peaks], atom_count)
            ambiguous = base is None
            if not ambiguous:
                for p in peaks:
                    p["atom_index"] -= base
            for p in peaks:
                idx = p["atom_index"]
                p["element"] = mol.GetAtomWithIdx(idx).GetSymbol() if not ambiguous and 0 <= idx < atom_count else None
            unusable = None
            if ambiguous:
                unusable = "ambiguous_atom_index_base"
            elif nucleus == "1H" and not has_explicit_h:
                unusable = "implicit_hydrogens_cannot_be_indexed"
            yield {
                "id": record_id(source, native, nucleus, solvent),
                "source": source, "native_id": native, "smiles": smiles, "inchikey": inchikey,
                "nucleus": nucleus, "solvent": solvent,
                "reference_compound": None,
                "field_mhz": float(field) if isinstance(field, (int, float)) else None,
                "temperature_k": float(temperature) if isinstance(temperature, (int, float)) else None,
                "predicted": "predicted" in str(props.get("Spectrum Type", "")).lower(),
                "atom_count": atom_count, "index_base_detected": base,
                "unusable_reason": unusable,
                "nuclei": [p for p in peaks if p.get("element")],
                "licence": "CC BY-SA (NMRShiftDB2)",
            }


def load(path, **kw):
    return list(iter_records(path, **kw))
