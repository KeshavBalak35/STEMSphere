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
            source=SourceRef(source_id=source_id, record_id=f"{source_id}-1", licence="CC BY 4.0"),
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
