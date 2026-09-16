"""Tests for the data platform: identity, catalog, policy, HTTP and ingestion."""
import json
from pathlib import Path

import pytest
from rdkit import Chem

from nmrx.data.http import HttpClient, ProviderUnavailable, RateLimiter, _backoff
from nmrx.data.identity import IdentityError, comparison, describe, payload_checksum, same_molecule
from nmrx.data.ingest import IngestionRun, ingest_bulk, write_bundle
from nmrx.data.policy import PolicyViolation, SourcePolicy
from nmrx.data.providers import available, get
from nmrx.data.providers.base import RawPayload
from nmrx.data.store import Catalog, deterministic_id

FIXTURES = Path(__file__).parent / "fixtures"

L_ALANINE = "C[C@H](N)C(=O)O"
D_ALANINE = "C[C@@H](N)C(=O)O"
FLAT_ALANINE = "CC(N)C(=O)O"


@pytest.fixture
def catalog():
    store = Catalog(":memory:")
    store.migrate()
    return store


# ---------------------------------------------------------------- identity

def test_enantiomers_are_never_merged():
    """The single most damaging identity mistake: a drug and its mirror image."""
    left, right = describe(L_ALANINE), describe(D_ALANINE)
    assert left["inchikey"] != right["inchikey"]
    assert not same_molecule(left, right)
    verdict = comparison(left, right)
    assert verdict["safe_to_merge"] is False
    assert verdict["relationship"] == "same_skeleton_different_form"
    assert verdict["requires_human_review"] is True
    assert left["skeleton_block"] == right["skeleton_block"]   # why a skeleton match is not enough


def test_undefined_stereochemistry_is_recorded_not_guessed():
    flat = describe(FLAT_ALANINE)
    assert flat["has_undefined_stereo"] and flat["undefined_stereocentre_indices"] == [1]
    assert not same_molecule(flat, describe(L_ALANINE))
    assert "undefined" in comparison(describe(L_ALANINE), flat)["reason"]


def test_salts_and_charge_states_are_distinguished():
    salt = describe("CC(=O)[O-].[Na+]")
    acid = describe("CC(=O)O")
    assert salt["component_count"] == 2 and acid["component_count"] == 1
    assert not same_molecule(salt, acid)
    assert len(salt["component_inchikeys"]) == 2


def test_isotopic_labelling_is_distinguished():
    labelled = describe("[13CH4]")
    plain = describe("C")
    assert labelled["is_isotopically_labelled"] and labelled["isotopes"] == [13]
    assert not plain["is_isotopically_labelled"]
    assert not same_molecule(labelled, plain)


def test_different_molecules_sharing_a_formula_are_not_merged():
    """C6H12O6 covers glucose, fructose and more, so formula is not an identity."""
    glucose = describe("OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O")
    fructose = describe("OC[C@H]1O[C@](O)(CO)[C@@H](O)[C@@H]1O")
    assert glucose["formula"] == fructose["formula"]
    assert comparison(glucose, fructose)["relationship"] == "different_molecule"


def test_unparseable_structure_raises_rather_than_returning_a_partial_identity():
    with pytest.raises(IdentityError):
        describe("not a molecule")
    with pytest.raises(IdentityError):
        describe("C(C)(C)(C)(C)C")          # pentavalent carbon


def test_payload_checksum_is_stable_and_order_independent():
    assert payload_checksum({"a": 1, "b": 2}) == payload_checksum({"b": 2, "a": 1})
    assert payload_checksum({"a": 1}) != payload_checksum({"a": 2})


# ------------------------------------------------------------------- store

def test_migrations_apply_and_reverse(catalog):
    assert catalog.current_version() == 1
    assert "molecule" in catalog.table_names() and "spectrum_peak" in catalog.table_names()
    assert catalog.rollback(0) == [1]
    assert catalog.current_version() == 0
    assert catalog.table_names() == ["schema_migration"]
    assert catalog.migrate() == [1]


def test_upsert_reports_inserted_unchanged_and_updated(catalog):
    row = {"id": "x", "name": "CC BY", "attribution_text": "a"}
    assert catalog.upsert("license", row) == "inserted"
    assert catalog.upsert("license", row) == "unchanged"
    assert catalog.upsert("license", dict(row, name="CC BY-SA")) == "updated"


def test_insert_only_columns_are_never_rewritten(catalog):
    base = {"id": "m1", "inchikey": "K", "inchi": "I", "skeleton_block": "S",
            "smiles_isomeric": "C", "smiles_canonical": "C", "formula": "CH4",
            "first_seen_at": "2020-01-01T00:00:00+00:00"}
    catalog.upsert("molecule", base)
    assert catalog.upsert("molecule", dict(base, first_seen_at="2026-01-01T00:00:00+00:00")) == "unchanged"
    assert catalog.one("SELECT first_seen_at FROM molecule")["first_seen_at"].startswith("2020")


def test_unknown_table_is_refused(catalog):
    with pytest.raises(ValueError, match="Unknown table"):
        catalog.upsert("definitely_not_a_table", {"id": "1"})


def test_deterministic_id_distinguishes_none_from_empty_string():
    assert deterministic_id("a", "b") == deterministic_id("a", "b")
    assert deterministic_id("a", None) != deterministic_id("a", "")


# ------------------------------------------------------------------ policy

def test_prohibited_sources_are_disabled_and_stay_disabled():
    policy = SourcePolicy()
    for provider in ("sdbs", "nist_webbook"):
        assert policy.get(provider)["enabled"] is False
        with pytest.raises(PolicyViolation, match="disabled by policy"):
            policy.check(provider, "api")
        with pytest.raises(PolicyViolation):
            policy.check(provider, "bulk")


def test_every_source_starts_commercially_unreviewed():
    """Unreviewed is not a synonym for allowed."""
    policy = SourcePolicy()
    for provider in ("pubchem", "nmrshiftdb2", "chembl", "rcsb_pdb", "bindingdb"):
        assert policy.get(provider)["commercial_use_state"] == "unreviewed"
    assert policy.get("nmrshiftdb2")["share_alike"] is True
    assert policy.get("chembl")["share_alike"] is True


def test_a_connector_can_be_disabled_immediately():
    policy = SourcePolicy()
    policy.check("pubchem", "api")
    policy.disable("pubchem", "suspended pending licence review")
    with pytest.raises(PolicyViolation, match="licence review"):
        policy.check("pubchem", "api")
    assert "pubchem.ncbi.nlm.nih.gov" not in policy.allowed_hosts()


def test_unknown_provider_is_refused_rather_than_defaulted():
    with pytest.raises(PolicyViolation, match="No policy entry"):
        SourcePolicy().check("some_random_site", "api")


def test_policy_round_trips_through_a_file(tmp_path):
    policy = SourcePolicy()
    policy.disable("chembl", "test")
    policy.save(tmp_path / "policy.json")
    assert SourcePolicy.load(tmp_path / "policy.json").get("chembl")["enabled"] is False


# -------------------------------------------------------------------- http

def test_rate_limiter_spaces_requests():
    waits, clock = [], [0.0]
    limiter = RateLimiter(2.0, clock=lambda: clock[0], sleeper=waits.append)
    assert limiter.acquire() == 0.0
    assert limiter.acquire() == pytest.approx(0.5)
    assert waits == [pytest.approx(0.5)]


def test_retries_then_succeeds_and_counts_the_retries():
    attempts = []

    def transport(url, headers, timeout):
        attempts.append(url)
        return (503, {}, b"busy") if len(attempts) < 3 else (200, {}, b'{"ok":true}')

    client = HttpClient("pubchem", transport=transport, sleeper=lambda s: None, jitter=lambda: 1.0)
    assert client.get_json("https://pubchem.ncbi.nlm.nih.gov/rest/pug/x") == {"ok": True}
    assert len(attempts) == 3 and client.stats["retries"] == 2


def test_gives_up_after_max_attempts():
    client = HttpClient("pubchem", transport=lambda u, h, t: (429, {}, b"no"),
                        sleeper=lambda s: None, jitter=lambda: 1.0, max_attempts=2)
    with pytest.raises(ProviderUnavailable, match="429"):
        client.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/x")


def test_client_identifies_itself():
    seen = {}

    def transport(url, headers, timeout):
        seen.update(headers)
        return 200, {}, b"ok"

    HttpClient("pubchem", transport=transport).get("https://pubchem.ncbi.nlm.nih.gov/x")
    assert "NMRx" in seen["User-Agent"]


def test_a_404_is_not_retried():
    attempts = []

    def transport(url, headers, timeout):
        attempts.append(url)
        return 404, {}, b"missing"

    client = HttpClient("pubchem", transport=transport, sleeper=lambda s: None)
    with pytest.raises(ProviderUnavailable):
        client.get("https://pubchem.ncbi.nlm.nih.gov/x")
    assert len(attempts) == 1


def test_backoff_honours_retry_after_and_otherwise_uses_jitter():
    assert _backoff(1, {"Retry-After": "7"}, lambda: 1.0) == 7.0
    assert _backoff(9, {"Retry-After": "9999"}, lambda: 1.0) == 60.0
    assert _backoff(3, {}, lambda: 0.5) == 2.0
    assert _backoff(3, {}, lambda: 0.0) == 0.0


def test_cache_prevents_a_second_request(tmp_path):
    attempts = []

    def transport(url, headers, timeout):
        attempts.append(url)
        return 200, {}, b"payload"

    client = HttpClient("pubchem", transport=transport, cache_dir=tmp_path)
    url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/x"
    assert client.get(url) == b"payload" and client.get(url) == b"payload"
    assert len(attempts) == 1 and client.stats["cache_hits"] == 1


def test_requests_are_confined_to_declared_hosts():
    client = HttpClient("pubchem", transport=lambda u, h, t: (200, {}, b"ok"))
    with pytest.raises(PolicyViolation, match="not declared"):
        client.get("https://evil.example.com/steal")


def test_health_distinguishes_policy_block_from_network_failure():
    blocked = HttpClient("sdbs", transport=lambda u, h, t: (200, {}, b"ok"))
    assert blocked.health("https://sdbs.db.aist.go.jp/x")["blocked_by"] == "policy"

    def dead(url, headers, timeout):
        raise ProviderUnavailable("refused")

    down = HttpClient("pubchem", transport=dead, sleeper=lambda s: None)
    assert down.health("https://pubchem.ncbi.nlm.nih.gov/x")["blocked_by"] == "network"


# --------------------------------------------------------------- providers

def _pubchem_payload():
    content = json.loads((FIXTURES / "pubchem" / "cid_2244.json").read_text())
    return RawPayload(provider="pubchem", source_id="2244", content=content,
                      retrieved_at="2026-01-01T00:00:00+00:00")


def _adapter(name="pubchem"):
    return get(name, transport=lambda u, h, t: (200, {}, b"{}"))


def test_both_first_phase_adapters_are_registered():
    assert available() == ["nmrshiftdb2", "pubchem"]


def test_pubchem_normalizes_a_real_record():
    bundle = _adapter().normalize(_pubchem_payload())
    assert bundle.usable
    assert bundle.identity["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert bundle.identity["formula"] == "C9H8O4"
    assert {n["name"] for n in bundle.names} >= {"aspirin", "acetylsalicylic acid"}
    assert bundle.xrefs[0]["external_id"] == "2244"
    assert bundle.spectra == []              # PubChem is not a spectral source
    assert bundle.issues == []


def test_pubchem_flags_a_structure_that_disagrees_with_its_own_key():
    content = json.loads((FIXTURES / "pubchem" / "cid_2244.json").read_text())
    content["properties"]["InChIKey"] = "WRONGWRONGWR-UHFFFAOYSA-N"
    bundle = _adapter().normalize(RawPayload(provider="pubchem", source_id="2244", content=content))
    codes = [i["code"] for i in bundle.issues]
    assert "inchikey_mismatch" in codes
    assert bundle.identity["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"   # local key wins


def test_pubchem_rejects_a_record_with_no_structure():
    bundle = _adapter().normalize(RawPayload(provider="pubchem", source_id="1",
                                             content={"properties": {"CID": 1}, "synonyms": []}))
    assert not bundle.usable and bundle.issues[0]["code"] == "no_structure"
    assert bundle.issues[0]["severity"] == "error"


def test_nmrshiftdb2_refuses_to_guess_an_unverified_rest_shape():
    from nmrx.data.providers.base import ProviderError
    adapter = _adapter("nmrshiftdb2")
    for call in (lambda: adapter.search("aspirin"), lambda: adapter.fetch("1"),
                 lambda: adapter.fetch_by_inchikey("X")):
        with pytest.raises(ProviderError, match="not implemented"):
            call()


def _write_sdf(path, entries):
    writer = Chem.SDWriter(str(path))
    for name, smiles, props in entries:
        mol = Chem.MolFromSmiles(smiles)
        mol.SetProp("_Name", name)
        for key, value in props.items():
            mol.SetProp(key, str(value))
        writer.write(mol)
    writer.close()


@pytest.fixture
def sdf(tmp_path):
    path = tmp_path / "bulk.sdf"
    _write_sdf(path, [
        ("measured", "CCO", {"nmrshiftdb2 ID": "100", "Spectrum 13C 0": "58.4;0.0;0|18.2;0.0;1|",
                             "Solvent": "0:Chloroform-D1 (CDCl3)", "NMRStandard": "0:TMS",
                             "Field Strength [MHz]": "0:125"}),
        ("calculated", "CCC", {"nmrshiftdb2 ID": "101", "Spectrum 13C 0": "15.6;0.0;0|16.1;0.0;1|",
                               "Solvent": "0:Unreported", "NMRModel": "0:Hartree-Fock",
                               "NMRBasisSet": "0:6-31G*", "Program": "0:Spartan"}),
    ])
    return path


def test_bulk_ingestion_labels_calculated_spectra_as_calculated(sdf):
    adapter = _adapter("nmrshiftdb2")
    bundles = {p.source_id.split("/")[0]: adapter.normalize(p) for p in adapter.iter_bulk(sdf)}
    measured, calculated = bundles["100"], bundles["101"]
    assert measured.spectra[0]["record_status"] == "measured"
    assert calculated.spectra[0]["record_status"] == "calculated"
    assert "calculated_not_measured" in [i["code"] for i in calculated.issues]
    assert calculated.spectra[0]["computed_program"] == "Spartan"


def test_unrecorded_metadata_becomes_null_rather_than_a_default(sdf):
    adapter = _adapter("nmrshiftdb2")
    bundles = {p.source_id.split("/")[0]: adapter.normalize(p) for p in adapter.iter_bulk(sdf)}
    good = bundles["100"].spectra[0]["conditions"]
    assert good["solvent"] == "CDCl3" and good["reference_compound"] == "TMS"
    assert good["frequency_mhz"] == 125.0
    bare = bundles["101"].spectra[0]["conditions"]
    assert bare["solvent"] is None and bare["reference_compound"] is None
    codes = [i["code"] for i in bundles["101"].issues]
    assert "solvent_unrecorded" in codes and "reference_unrecorded" in codes


def test_bulk_mode_is_policy_checked(sdf):
    policy = SourcePolicy()
    policy.disable("nmrshiftdb2", "paused")
    adapter = get("nmrshiftdb2", policy=policy, transport=lambda u, h, t: (200, {}, b"{}"))
    with pytest.raises(PolicyViolation):
        list(adapter.iter_bulk(sdf))


# --------------------------------------------------------------- ingestion

def test_ingestion_is_idempotent(catalog, sdf):
    adapter = _adapter("nmrshiftdb2")
    first = ingest_bulk(catalog, adapter, adapter.iter_bulk(sdf))
    counts_after_first = catalog.counts()
    second = ingest_bulk(catalog, adapter, adapter.iter_bulk(sdf))

    assert first["inserted"] > 0
    assert second["inserted"] == 0 and second["updated"] == 0
    assert second["unchanged"] > 0
    ignore = {"ingestion_run"}
    assert {k: v for k, v in catalog.counts().items() if k not in ignore} == \
           {k: v for k, v in counts_after_first.items() if k not in ignore}


def test_a_rejected_record_is_stored_with_its_reason(catalog, tmp_path):
    path = tmp_path / "bad.sdf"
    _write_sdf(path, [("proton", "CCO", {"nmrshiftdb2 ID": "1",
                                         "Spectrum 1H 0": "3.7;0.0;0|", "Solvent": "0:CDCl3"})])
    adapter = _adapter("nmrshiftdb2")
    report = ingest_bulk(catalog, adapter, adapter.iter_bulk(path))
    assert report["rejected"] == 1 and catalog.counts()["molecule"] == 0
    record = catalog.one("SELECT validation_state, rejection_reason FROM source_record")
    assert record["validation_state"] == "rejected"
    assert "implicit_hydrogens" in record["rejection_reason"]
    assert catalog.one("SELECT count(*) n FROM validation_issue WHERE severity='error'")["n"] == 1


def test_provenance_is_attached_to_every_curated_row(catalog):
    adapter, payload = _adapter(), _pubchem_payload()
    run = IngestionRun(catalog, "pubchem")
    write_bundle(catalog, adapter, payload, adapter.normalize(payload), run)
    record = catalog.one("SELECT * FROM source_record")
    assert record["provider"] == "pubchem" and record["source_id"] == "2244"
    assert record["payload_checksum"] and record["parser_version"].startswith("pubchem:")
    assert record["retrieved_at"] == "2026-01-01T00:00:00+00:00"
    assert record["license_id"] == "license:pubchem"
    assert catalog.one("SELECT attribution_text FROM license")["attribution_text"].startswith("Data from PubChem")
    for table in ("molecule_name", "molecule_xref"):
        assert catalog.one("SELECT count(*) n FROM %s WHERE source_record_id=?" % table,
                           (record["id"],))["n"] > 0


def test_a_changed_payload_creates_a_new_source_record(catalog):
    """Checksum is part of the key, so a source editing a record is visible."""
    adapter = _adapter()
    original = _pubchem_payload()
    write_bundle(catalog, adapter, original, adapter.normalize(original))
    edited = json.loads(json.dumps(original.content))
    edited["properties"]["IUPACName"] = "changed name"
    revised = RawPayload(provider="pubchem", source_id="2244", content=edited)
    write_bundle(catalog, adapter, revised, adapter.normalize(revised))
    assert catalog.one("SELECT count(*) n FROM source_record")["n"] == 2
    assert catalog.one("SELECT count(*) n FROM molecule")["n"] == 1     # still one molecule


def test_run_records_checkpoint_and_final_status(catalog, sdf):
    adapter = _adapter("nmrshiftdb2")
    run = IngestionRun(catalog, "nmrshiftdb2", mode="bulk")
    run.save_checkpoint("100/13C/0")
    run.finish("succeeded")
    stored = catalog.one("SELECT * FROM ingestion_run")
    assert stored["status"] == "succeeded" and stored["checkpoint"] == "100/13C/0"
    assert stored["finished_at"] is not None


def test_a_failing_run_is_marked_failed_not_left_running(catalog):
    adapter = _adapter("nmrshiftdb2")

    def exploding():
        yield from ()
        raise RuntimeError("source went away")

    with pytest.raises(RuntimeError):
        ingest_bulk(catalog, adapter, exploding())
    assert catalog.one("SELECT status, notes FROM ingestion_run")["status"] == "failed"
