"""Tests for the controlled file inbox: the import route that needs no network."""
from pathlib import Path

import pytest
from rdkit import Chem

from nmrx.data.inbox import (Inbox, Quarantined, import_file, import_pending,
                             parse_assignment_csv, parse_jcamp, parse_nmredata, sniff)
from nmrx.data.store import Catalog

CSV_HEADER = "smiles,atom_index,shift_ppm,nucleus,solvent,reference_compound,temperature_k\n"


@pytest.fixture
def catalog():
    store = Catalog(":memory:")
    store.migrate()
    return store


@pytest.fixture
def inbox(tmp_path):
    return Inbox(tmp_path / "inbox")


def write_csv(path, rows=("CCO,0,58.4,13C,CDCl3,TMS,298", "CCO,1,18.2,13C,CDCl3,TMS,298")):
    path.write_text(CSV_HEADER + "\n".join(rows) + "\n")
    return path


def write_nmredata(path, tags=None, smiles="CC(=O)Oc1ccccc1C(=O)O"):
    writer = Chem.SDWriter(str(path))
    mol = Chem.MolFromSmiles(smiles)
    mol.SetProp("_Name", "test")
    for key, value in (tags or {}).items():
        mol.SetProp(key, str(value))
    writer.write(mol)
    writer.close()
    return path


# ------------------------------------------------------------------ sniff

def test_type_is_decided_by_content_not_extension(tmp_path):
    """A file named .sdf that contains a CSV must not be parsed as an SDF."""
    disguised = tmp_path / "actually_a_csv.sdf"
    write_csv(disguised)
    assert sniff(disguised) == "csv"


def test_executable_formats_are_refused_outright(tmp_path):
    for suffix in (".pkl", ".exe", ".sh", ".js", ".xlsm"):
        path = tmp_path / ("payload" + suffix)
        path.write_bytes(b"anything at all")
        with pytest.raises(Quarantined, match="executable content"):
            sniff(path)


def test_empty_and_oversized_files_are_refused(tmp_path, monkeypatch):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(Quarantined, match="empty"):
        sniff(empty)

    import nmrx.data.inbox as module
    monkeypatch.setattr(module, "MAX_BYTES", 10)
    big = write_csv(tmp_path / "big.csv")
    with pytest.raises(Quarantined, match="import limit"):
        sniff(big)


def test_unrecognisable_content_is_refused_rather_than_guessed(tmp_path):
    path = tmp_path / "mystery.dat"
    path.write_text("just some prose with no structure whatsoever")
    with pytest.raises(Quarantined, match="Could not identify"):
        sniff(path)


def test_nmredata_is_distinguished_from_plain_sdf(tmp_path):
    plain = write_nmredata(tmp_path / "plain.sdf")
    tagged = write_nmredata(tmp_path / "tagged.sdf",
                            {"NMREDATA_VERSION": "1.1", "NMREDATA_SOLVENT": "CDCl3",
                             "NMREDATA_1D_13C": "170.5, 1\n21.0, 2\n"})
    assert sniff(plain) == "sdf"
    assert sniff(tagged) == "nmredata"      # tags sit past the first 8 KB


def test_jcamp_is_recognised(tmp_path):
    path = tmp_path / "s.jdx"
    path.write_text("##TITLE=ethanol\n##JCAMP-DX=4.24\n##XYDATA=(X++(Y..Y))\n0 1\n")
    assert sniff(path) == "jcamp"


# ----------------------------------------------------------------- parsers

def test_nmredata_carries_conditions_and_assignments(tmp_path):
    path = write_nmredata(tmp_path / "a.sdf", {
        "NMREDATA_VERSION": "1.1", "NMREDATA_SOLVENT": "CDCl3",
        "NMREDATA_TEMPERATURE": "300", "NMREDATA_FREQUENCY": "400.13",
        "NMREDATA_REFERENCE": "TMS", "NMREDATA_1D_13C": "170.5, 1\n21.0, 2\n"})
    record = parse_nmredata(path)[0]
    assert record["solvent"] == "CDCl3" and record["temperature_k"] == 300.0
    assert record["frequency_mhz"] == 400.13 and record["reference_compound"] == "TMS"
    assert record["spectra"][0]["nucleus"] == "13C"
    assert [p["observed_shift_ppm"] for p in record["spectra"][0]["peaks"]] == [170.5, 21.0]
    assert record["spectra"][0]["peaks"][0]["atom_index"] == 0     # one-based in file


def test_nmredata_drops_peaks_it_cannot_resolve(tmp_path):
    path = write_nmredata(tmp_path / "b.sdf", {
        "NMREDATA_VERSION": "1.1",
        "NMREDATA_1D_13C": "170.5, 1\nnot a number, 2\n55.0, 9999\n# a comment\n"})
    peaks = parse_nmredata(path)[0]["spectra"][0]["peaks"]
    assert len(peaks) == 1 and peaks[0]["observed_shift_ppm"] == 170.5


def test_csv_requires_its_three_essential_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("smiles,shift_ppm\nCCO,58.4\n")
    with pytest.raises(Quarantined, match="atom_index"):
        parse_assignment_csv(path)


def test_csv_groups_rows_into_one_spectrum_per_molecule(tmp_path):
    path = write_csv(tmp_path / "c.csv", [
        "CCO,0,58.4,13C,CDCl3,TMS,298", "CCO,1,18.2,13C,CDCl3,TMS,298",
        "c1ccccc1,0,128.5,13C,CDCl3,TMS,298"])
    records = parse_assignment_csv(path)
    assert len(records) == 2
    ethanol = next(r for r in records if r["smiles"] == "CCO")
    assert len(ethanol["peaks"]) == 2 and ethanol["reference_compound"] == "TMS"


def test_jcamp_headers_are_read(tmp_path):
    path = tmp_path / "s.jdx"
    path.write_text("##TITLE=ethanol\n##JCAMP-DX=4.24\n##DATA TYPE=NMR SPECTRUM\n"
                    "##.OBSERVE NUCLEUS=^13C\n##SOLVENT NAME=CDCl3\n##XYDATA=(X++(Y..Y))\n0 1\n")
    header = parse_jcamp(path)
    assert header["title"] == "ethanol" and header["solvent"] == "CDCl3"


# --------------------------------------------------------------- importing

def test_csv_import_lands_in_the_catalog_with_conditions(catalog, inbox, tmp_path):
    report = import_file(catalog, write_csv(tmp_path / "d.csv"), inbox=inbox)
    assert report["kind"] == "csv" and report["imported"] == 1 and not report["quarantined"]
    row = catalog.one("SELECT c.solvent, c.reference_compound, c.temperature_k, s.record_status "
                      "FROM spectrum s JOIN experimental_conditions c ON c.id=s.conditions_id")
    assert row["solvent"] == "CDCl3" and row["reference_compound"] == "TMS"
    assert row["temperature_k"] == 298.0 and row["record_status"] == "measured"
    assert catalog.one("SELECT count(*) n FROM spectrum_peak")["n"] == 2


def test_missing_conditions_are_reported_not_invented(catalog, inbox, tmp_path):
    path = tmp_path / "bare.csv"
    path.write_text("smiles,atom_index,shift_ppm\nCCO,0,58.4\nCCO,1,18.2\n")
    report = import_file(catalog, path, inbox=inbox)
    assert report["imported"] == 1
    assert {"solvent_unrecorded", "reference_unrecorded"} <= set(report["issues"])
    row = catalog.one("SELECT solvent, reference_compound FROM experimental_conditions")
    assert row["solvent"] is None and row["reference_compound"] is None


def test_a_calculated_record_is_labelled_calculated(catalog, inbox, tmp_path):
    """NMReDATA states a level of theory when the shifts were computed."""
    path = write_nmredata(tmp_path / "calc.sdf", {
        "NMREDATA_VERSION": "1.1", "NMREDATA_SOLVENT": "CDCl3",
        "NMREDATA_LEVEL": "B3LYP/6-31G(d) GIAO",
        "NMREDATA_1D_13C": "170.5, 1\n21.0, 2\n"})
    report = import_file(catalog, path, inbox=inbox)
    assert report["imported"] == 1
    assert catalog.one("SELECT record_status FROM spectrum")["record_status"] == "calculated"
    assert "not_a_measurement" in report["issues"]


def test_jcamp_is_catalogued_but_not_treated_as_an_assigned_spectrum(catalog, inbox, tmp_path):
    path = tmp_path / "s.jdx"
    path.write_text("##TITLE=x\n##JCAMP-DX=4.24\n##SOLVENT NAME=CDCl3\n##XYDATA=(X++(Y..Y))\n0 1\n")
    report = import_file(catalog, path, inbox=inbox)
    assert report["imported"] == 0 and not report["quarantined"]
    assert "no per-atom assignment" in report["detail"]
    assert catalog.counts()["spectrum"] == 0


def test_a_bad_structure_is_rejected_with_a_reason(catalog, inbox, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(CSV_HEADER + "not-a-molecule,0,58.4,13C,CDCl3,TMS,298\n")
    report = import_file(catalog, path, inbox=inbox)
    assert report["rejected"] == 1 and report["imported"] == 0
    assert "unresolvable_structure" in report["issues"]
    record = catalog.one("SELECT validation_state, rejection_reason FROM source_record")
    assert record["validation_state"] == "rejected" and "unresolvable" in record["rejection_reason"]


def test_quarantine_writes_a_readable_explanation(catalog, inbox, tmp_path):
    path = tmp_path / "thing.pkl"
    path.write_bytes(b"\x80\x04 pretend pickle")
    report = import_file(catalog, path, inbox=inbox)
    assert report["quarantined"]
    note = inbox.quarantine / "thing.pkl.txt"
    assert note.exists() and "executable content" in note.read_text()
    assert "was not moved or changed" in note.read_text()


def test_the_original_file_is_never_touched(catalog, inbox, tmp_path):
    path = write_csv(tmp_path / "keep.csv")
    before = path.read_bytes()
    import_file(catalog, path, inbox=inbox)
    assert path.exists() and path.read_bytes() == before
    assert len(list(inbox.storage.iterdir())) == 1        # a copy was taken


def test_importing_twice_is_idempotent(catalog, inbox, tmp_path):
    path = write_csv(tmp_path / "twice.csv")
    import_file(catalog, path, inbox=inbox)
    counts = catalog.counts()
    import_file(catalog, path, inbox=inbox)
    assert {k: v for k, v in catalog.counts().items() if k != "ingestion_run"} == \
           {k: v for k, v in counts.items() if k != "ingestion_run"}


def test_provenance_records_the_file_it_came_from(catalog, inbox, tmp_path):
    import_file(catalog, write_csv(tmp_path / "prov.csv"), inbox=inbox, source_note="from a paper")
    record = catalog.one("SELECT * FROM source_record")
    assert record["provider"] == "inbox" and record["payload_checksum"]
    assert record["source_release"] == "from a paper"
    assert record["parser_version"].startswith("inbox:csv")
    licence = catalog.one("SELECT * FROM license WHERE id='license:inbox'")
    assert licence["commercial_use_state"] == "unreviewed"
    assert "responsible for holding the rights" in licence["attribution_text"]


def test_batch_import_processes_the_incoming_folder(catalog, inbox, tmp_path):
    write_csv(inbox.incoming / "one.csv")
    write_csv(inbox.incoming / "two.csv", ["c1ccccc1,0,128.5,13C,CDCl3,TMS,298",
                                           "c1ccccc1,1,128.5,13C,CDCl3,TMS,298"])
    reports = import_pending(catalog, inbox=inbox)
    assert len(reports) == 2 and sum(r["imported"] for r in reports) == 2
    assert catalog.counts()["molecule"] == 2
