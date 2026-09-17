"""Regressions for defects found by adversarially reviewing this package.

Each test here corresponds to a bug that was real, reproduced, and fixed. They are grouped
by what the bug would have cost, because that is what makes them worth keeping.
"""

import io
import json
import threading
import unittest
import urllib.error

from nmrx.model.dedup import cluster_records, experiment_key
from nmrx.model.dossier import build
from nmrx.model.provenance import IdentityMatch, Lineage, SpectrumState
from nmrx.model.records import (
    ExperimentalConditions,
    MoleculeIdentity,
    NMRRecord,
    ShiftAssignment,
    SourceRef,
)
from nmrx.sources.http import BoundedHttpClient, redact
from nmrx.sources.policy import PolicyDenied, load_policy

KEY_A = "AAAAAAAAAAAAAA-BBBBBBBBBB-N"
KEY_B = "QQQQQQQQQQQQQQ-BBBBBBBBBB-N"


class TestSecretsNeverReachTheLog(unittest.TestCase):
    """The request log is a durable artifact that gets committed."""

    def test_userinfo_is_stripped_before_recording(self):
        self.assertEqual(redact("https://user:SECRET@h.example/x?a=1"), "https://***@h.example/x?a=1")

    def test_a_plain_url_is_left_alone(self):
        self.assertEqual(redact("https://h.example/x"), "https://h.example/x")

    def test_a_port_survives_redaction(self):
        self.assertEqual(redact("https://u:p@h.example:8443/x"), "https://***@h.example:8443/x")

    def test_a_refused_credentialled_url_does_not_leak_into_the_log(self):
        """Refusing the URL for carrying credentials, then logging them, defeats the point."""
        client = BoundedHttpClient(load_policy())
        attempt = client.get("https://user:SECRET@pubchem.ncbi.nlm.nih.gov/x", purpose="t")
        self.assertEqual(attempt.reason_code, "CREDENTIALS_IN_URL")
        self.assertNotIn("SECRET", json.dumps(client.log.to_dict()))
        self.assertNotIn("SECRET", attempt.url)


class _Resp(io.BytesIO):
    status = 200

    class _H(dict):
        def get(self, k, d=None):
            return d
    headers = _H()

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestCapsCannotBeWidenedByACaller(unittest.TestCase):
    def test_a_larger_max_bytes_cannot_raise_the_policy_cap(self):
        """Otherwise any call site could opt itself out of the limit."""
        policy = load_policy()

        class _O:
            def open(self, req, timeout=None):
                return _Resp(b"z" * 9_000_000)

        client = BoundedHttpClient(policy, opener_factory=lambda: _O(), clock=lambda: 0.0)
        client.budget.caps.min_seconds_between_requests_per_host = 0.0
        attempt = client.get("https://pubchem.ncbi.nlm.nih.gov/x", source_id="pubchem",
                             purpose="t", max_bytes=8_000_000)
        self.assertLessEqual(attempt.bytes_downloaded, policy.caps.max_bytes_per_response + 1)

    def test_a_smaller_max_bytes_still_tightens(self):
        policy = load_policy()

        class _O:
            def open(self, req, timeout=None):
                return _Resp(b"z" * 100_000)

        client = BoundedHttpClient(policy, opener_factory=lambda: _O(), clock=lambda: 0.0)
        client.budget.caps.min_seconds_between_requests_per_host = 0.0
        attempt = client.get("https://pubchem.ncbi.nlm.nih.gov/x", source_id="pubchem",
                             purpose="t", max_bytes=500)
        self.assertEqual(attempt.bytes_downloaded, 501)


class TestRequestCapHoldsUnderConcurrency(unittest.TestCase):
    def test_the_cap_is_exact_with_many_concurrent_callers(self):
        """Check-then-increment in two lock acquisitions lets N in-flight callers overshoot."""
        budget = load_policy().new_budget()
        budget.caps.max_requests_per_job = 10
        granted = []

        def worker():
            try:
                budget.reserve("h")
                granted.append(1)
            except PolicyDenied:
                pass

        threads = [threading.Thread(target=worker) for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(granted), 10)
        self.assertEqual(budget.requests_made, 10)


class TestUnidentifiedRecordsDoNotMerge(unittest.TestCase):
    def test_two_different_unpinned_molecules_are_two_experiments(self):
        """An all-UNKNOWN key would otherwise merge every unidentified record into one."""
        a = NMRRecord(molecule=MoleculeIdentity(smiles="CC"), source=SourceRef(source_id="x"))
        b = NMRRecord(molecule=MoleculeIdentity(smiles="c1ccccc1"), source=SourceRef(source_id="y"))
        self.assertNotEqual(experiment_key(a), experiment_key(b))
        self.assertEqual(len(cluster_records([a, b])), 2)

    def test_an_unidentified_record_does_not_absorb_an_identified_one(self):
        a = NMRRecord(molecule=MoleculeIdentity(), source=SourceRef(source_id="x"))
        b = NMRRecord(molecule=MoleculeIdentity(inchikey=KEY_A), source=SourceRef(source_id="y"))
        self.assertEqual(len(cluster_records([a, b])), 2)


class TestSupportCountingIsNotInflated(unittest.TestCase):
    def _rec(self, source_id):
        return NMRRecord(
            molecule=MoleculeIdentity(inchikey=KEY_A, atom_count=2),
            source=SourceRef(source_id=source_id, record_id=f"{source_id}-1",
                             licence="CC BY 4.0", lineage=Lineage.ORIGINAL_EXPERIMENT),
            nucleus="13C",
            conditions=ExperimentalConditions(solvent="CDCl3", temperature_k=298.0,
                                              reference_compound="TMS"),
            shifts=[ShiftAssignment(0, "C", 10.0), ShiftAssignment(1, "C", 20.0)],
        )

    def test_two_mirrors_of_an_absent_upstream_are_still_one_result(self):
        """MoNA and GNPS both re-serve MassBank. Without MassBank present they are not
        mirrors *of each other* in a pairwise list, so both used to count."""
        clusters = cluster_records([self._rec("mona"), self._rec("gnps")])
        self.assertEqual(clusters[0].independent_support_count(), 1)

    def test_genuinely_independent_labs_still_corroborate(self):
        clusters = cluster_records([self._rec("nmrshiftdb2"), self._rec("bmrb")])
        self.assertEqual(clusters[0].independent_support_count(), 2)

    def test_a_mixed_cluster_counts_only_the_distinct_groups(self):
        clusters = cluster_records([
            self._rec("massbank"), self._rec("mona"), self._rec("gnps"), self._rec("nmrshiftdb2"),
        ])
        self.assertEqual(clusters[0].independent_support_count(), 2)


class TestIdentityComparisonIsHonest(unittest.TestCase):
    def test_two_unrelated_molecules_are_not_called_connectivity_matches(self):
        a = MoleculeIdentity(inchikey=KEY_A)
        self.assertIs(a.compare(MoleculeIdentity(inchikey=KEY_B)), IdentityMatch.UNRELATED)

    def test_an_unpinned_structure_yields_an_unknown_relation(self):
        a = MoleculeIdentity(inchikey=KEY_A)
        self.assertIs(a.compare(MoleculeIdentity()), IdentityMatch.UNKNOWN_RELATION)

    def test_a_shared_skeleton_is_still_connectivity_only(self):
        a = MoleculeIdentity(inchikey=KEY_A)
        other = MoleculeIdentity(inchikey="AAAAAAAAAAAAAA-ZZZZZZZZZZ-N")
        self.assertIs(a.compare(other), IdentityMatch.CONNECTIVITY_ONLY)

    def test_neither_new_verdict_counts_as_related(self):
        self.assertFalse(IdentityMatch.UNRELATED.is_related)
        self.assertFalse(IdentityMatch.UNKNOWN_RELATION.is_related)
        self.assertTrue(IdentityMatch.CONNECTIVITY_ONLY.is_related)

    def test_identity_is_hashable_despite_carrying_external_ids(self):
        """A frozen dataclass with a dict field raises on the generated hash."""
        m = MoleculeIdentity(inchikey=KEY_A, external_ids={"pubchem": "2244"})
        self.assertIsInstance(hash(m), int)
        self.assertEqual(len({m, m}), 1)

    def test_hash_is_on_the_structure_not_on_which_databases_indexed_it(self):
        """Equality still compares every field; only the hash is narrowed."""
        a = MoleculeIdentity(inchikey=KEY_A, external_ids={"pubchem": "2244"})
        b = MoleculeIdentity(inchikey=KEY_A, external_ids={})
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, b)


class TestAtomCountCoercion(unittest.TestCase):
    def test_a_string_atom_count_still_bounds_the_range_check(self):
        """A source reporting the count as text must not disable the check."""
        rec = NMRRecord(
            molecule=MoleculeIdentity(inchikey=KEY_A, atom_count="4"),
            source=SourceRef(source_id="s"),
            shifts=[ShiftAssignment(99, "C", 1.0)],
        )
        self.assertTrue(any("outside" in p for p in rec.atom_index_problems()))

    def test_an_uninterpretable_atom_count_does_not_crash(self):
        rec = NMRRecord(
            molecule=MoleculeIdentity(inchikey=KEY_A, atom_count="many"),
            source=SourceRef(source_id="s"),
            shifts=[ShiftAssignment(99, "C", 1.0)],
        )
        self.assertEqual(rec.atom_index_problems(), [])


class TestDossierSerialisation(unittest.TestCase):
    def test_a_dossier_with_unknowns_is_json_serialisable(self):
        """UNKNOWN is a sentinel object; emitting it raw makes the dossier unusable."""
        dossier = build(MoleculeIdentity(smiles="CC"), [])
        self.assertIn('"inchikey": null', json.dumps(dossier.to_dict(), indent=1))

    def test_a_dossier_with_records_is_json_serialisable(self):
        rec = NMRRecord(
            molecule=MoleculeIdentity(inchikey=KEY_A, atom_count=2),
            source=SourceRef(source_id="nmrshiftdb2"),
            identity_match=IdentityMatch.EXACT,
            shifts=[ShiftAssignment(0, "C", 1.0)],
        )
        json.dumps(build(MoleculeIdentity(inchikey=KEY_A), [rec]).to_dict())

    def test_a_record_with_a_broken_atom_mapping_is_not_published(self):
        """Incomplete data is fine to show with a caveat. Wrong data is not."""
        rec = NMRRecord(
            molecule=MoleculeIdentity(inchikey=KEY_A, atom_count=2),
            source=SourceRef(source_id="nmrshiftdb2", licence="CC BY 4.0"),
            nucleus="13C",
            spectrum_state=SpectrumState.ASSIGNED_PEAKS,
            identity_match=IdentityMatch.EXACT,
            conditions=ExperimentalConditions(solvent="CDCl3", temperature_k=298.0,
                                             reference_compound="TMS"),
            shifts=[ShiftAssignment(0, "C", 1.0), ShiftAssignment(0, "C", 2.0)],
        )
        dossier = build(MoleculeIdentity(inchikey=KEY_A), [rec])
        self.assertEqual(dossier.section("measured_nmr_exact").evidence, [])


if __name__ == "__main__":
    unittest.main()


class TestMappingsCannotFabricate(unittest.TestCase):
    """The core invariant, enforced at the mapping layer."""

    def _plan(self, mapping):
        from nmrx.adapters.base import AdapterPlan
        return AdapterPlan.from_dict({"source_id": "nmrshiftdb2", "schema_confirmed": False,
                                      "record_mapping": mapping})

    def test_a_default_in_a_mapping_is_refused(self):
        """A default turns a field the source omitted into a value it never stated."""
        from nmrx.adapters.base import AdapterError, _field
        with self.assertRaises(AdapterError) as ctx:
            _field({}, {"path": "license", "default": "CC0"})
        self.assertIn("defaults are forbidden", str(ctx.exception))

    def test_const_and_path_together_are_refused(self):
        from nmrx.adapters.base import AdapterError, _field
        with self.assertRaises(AdapterError):
            _field({}, {"path": "license", "const": "CC0"})

    def test_const_alone_still_works(self):
        from nmrx.adapters.base import _field
        self.assertEqual(_field({}, {"const": "CC0"}), "CC0")

    def test_an_absent_licence_stays_unknown(self):
        from nmrx.adapters.base import _field
        from nmrx.model.provenance import UNKNOWN
        self.assertIs(_field({}, {"path": "license"}), UNKNOWN)


class TestNonFiniteShiftsAreRejected(unittest.TestCase):
    def test_nan_and_infinity_never_become_chemical_shifts(self):
        """They parse as floats and would poison every downstream average and export."""
        from nmrx.adapters.base import AdapterPlan, map_payload
        plan = AdapterPlan.from_dict({
            "source_id": "nmrshiftdb2", "schema_confirmed": False,
            "record_mapping": {"records_path": "", "shifts": {
                "path": "peaks", "shift_ppm": {"path": "ppm", "transform": "float"},
                "element": {"path": "el"}, "atom_index": {"path": "atom", "transform": "int"}}},
        })
        payload = {"peaks": [
            {"el": "C", "ppm": "NaN", "atom": 0},
            {"el": "C", "ppm": "inf", "atom": 1},
            {"el": "C", "ppm": "-Infinity", "atom": 2},
            {"el": "C", "ppm": "12.5", "atom": 3},
        ]}
        shifts = map_payload(payload, plan)[0].shifts
        self.assertEqual([s.shift_ppm for s in shifts], [12.5])

    def test_the_float_transform_is_total(self):
        from nmrx.adapters.base import TRANSFORMS
        from nmrx.model.provenance import UNKNOWN
        for bad in ("nan", "inf", "-inf", "abc", None, [], {}):
            with self.subTest(bad=bad):
                self.assertIs(TRANSFORMS["float"](bad), UNKNOWN)


class TestEmptyCollectionsAreNotFalsyBugs(unittest.TestCase):
    """SourceRegistry defines __len__, so an empty one is falsy."""

    def test_an_empty_registry_is_not_swapped_for_the_on_disk_one(self):
        from nmrx.reports.ranking import rank_next_connectors
        from nmrx.sources.registry import SourceRegistry
        self.assertEqual(rank_next_connectors(SourceRegistry([])), [])

    def test_an_empty_registry_yields_no_rights_blockers(self):
        from nmrx.reports.blockers import build
        from nmrx.sources.registry import SourceRegistry
        report = build(probe={"results": []}, registry=SourceRegistry([]))
        rights = [b for b in report["rights_and_policy_blockers"] if b["layer"] == "provider_rights"]
        self.assertEqual(rights, [])

    def test_limit_zero_means_zero_not_unlimited(self):
        from nmrx.reports.ranking import rank_next_connectors
        from nmrx.sources.registry import load_registry
        self.assertEqual(rank_next_connectors(load_registry(), limit=0), [])


class TestMalformedInputDoesNotCrash(unittest.TestCase):
    def test_a_registry_entry_without_an_id_gives_a_clear_error(self):
        from nmrx.sources.registry import RegistryError, SourceRegistry
        with self.assertRaises(RegistryError) as ctx:
            SourceRegistry([{"name": "x"}])
        self.assertIn("no 'id' key", str(ctx.exception))

    def test_wrongly_typed_sections_become_violations_not_exceptions(self):
        from nmrx.sources.registry import SourceRegistry
        problems = SourceRegistry([{"id": "a", "rights": "oops",
                                    "nmr_relevance": 5, "access": []}]).validate()
        self.assertTrue(any("rights must be an object" in p for p in problems))
        self.assertTrue(any("nmr_relevance must be an object" in p for p in problems))

    def test_a_truncated_probe_report_still_yields_its_blockers(self):
        from nmrx.reports.blockers import from_probe
        blockers = from_probe({"results": [
            None,
            {"classification": "blocked_by_environment_network_policy"},   # no host
            {"classification": "blocked_by_environment_network_policy", "host": "h.example"},
        ]})
        self.assertEqual([b.host for b in blockers], ["h.example"])

    def test_an_unterminated_path_index_reads_nothing(self):
        from nmrx.adapters.base import get_path
        from nmrx.model.provenance import UNKNOWN
        self.assertIs(get_path({"a": [{"b": 1}]}, "a[0.b"), UNKNOWN)


class TestCliFailsReadably(unittest.TestCase):
    def test_an_unknown_source_id_exits_non_zero_without_a_traceback(self):
        import contextlib
        from nmrx.cli import main
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = main(["registry", "nosuchsource"])
        self.assertEqual(code, 1)
        self.assertIn("no source with id", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_a_missing_data_file_is_reported_not_raised(self):
        import contextlib
        from unittest import mock
        from nmrx.cli import main
        err = io.StringIO()
        with mock.patch("nmrx.cli.load_registry", side_effect=FileNotFoundError(2, "x", "gone.json")):
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = main(["registry"])
        self.assertEqual(code, 2)
        self.assertIn("not found", err.getvalue())
