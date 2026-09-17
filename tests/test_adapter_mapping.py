"""The mapping engine turns a declared field mapping into records -- and nothing more.

All fixtures here are synthetic (see tests/fixtures/README.md). No real API response has been
observed from this environment, which is exactly why parsing is declarative: when a real
schema is finally confirmed, the mapping JSON changes and this engine does not.
"""

import json
import tempfile
import unittest
from pathlib import Path

from nmrx.adapters.base import (
    AdapterError,
    AdapterPlan,
    SchemaUnconfirmed,
    SourceAdapter,
    get_path,
    map_payload,
)
from nmrx.model.provenance import UNKNOWN, Lineage, SpectrumState, is_known

FIXTURES = Path(__file__).resolve().parent / "fixtures"

PLAN = {
    "source_id": "nmrshiftdb2",
    "name": "synthetic test plan",
    "schema_confirmed": False,
    "hosts_required": ["nmrshiftdb.nmr.uni-koeln.de"],
    "routes": [
        {"purpose": "by_inchikey", "url_template": "https://nmrshiftdb.nmr.uni-koeln.de/x/{inchikey}",
         "provenance": "inferred", "doc_link": "https://nmrshiftdb.nmr.uni-koeln.de/api-docs/",
         "response_format": "json", "must_confirm_live": "path shape unverified"}
    ],
    "blocking_unknowns": ["no real response has been read"],
    "record_mapping": {
        "records_path": "results",
        "molecule": {
            "inchikey": {"path": "structure.inchikey"},
            "smiles": {"path": "structure.smiles"},
            "formula": {"path": "structure.formula"},
            "atom_count": {"path": "structure.heavy_atoms", "transform": "int"},
            "external_ids": {"native": {"path": "id"}},
        },
        "source": {
            "record_id": {"path": "id"},
            "url": {"path": "url"},
            "licence": {"path": "licence"},
        },
        "nucleus": {"path": "spectrum.nucleus"},
        "conditions": {
            "solvent": {"path": "spectrum.solvent"},
            "temperature_k": {"path": "spectrum.temperature_celsius", "transform": "celsius_to_kelvin"},
            "reference_compound": {"path": "spectrum.reference"},
            "spectrometer_frequency_mhz": {"path": "spectrum.frequency", "transform": "float"},
        },
        "shifts": {
            "path": "spectrum.peaks",
            "atom_index": {"path": "atom", "transform": "int"},
            "element": {"path": "el"},
            "shift_ppm": {"path": "ppm", "transform": "float"},
            "multiplicity": {"path": "mult"},
        },
    },
}


def _payload():
    return json.loads((FIXTURES / "synthetic_assigned_spectrum.json").read_text())


def _plan():
    return AdapterPlan.from_dict(PLAN)


class TestPathAccess(unittest.TestCase):
    def test_dotted_and_indexed_paths(self):
        doc = {"a": {"b": [{"c": 5}]}}
        self.assertEqual(get_path(doc, "a.b[0].c"), 5)

    def test_a_missing_step_yields_unknown_not_an_error(self):
        doc = {"a": {}}
        for path in ("a.b.c", "a.b[0]", "zzz", "a.b[9].c"):
            with self.subTest(path=path):
                self.assertIs(get_path(doc, path), UNKNOWN)


class TestMappingProducesRecords(unittest.TestCase):
    def setUp(self):
        self.records = map_payload(_payload(), _plan())

    def test_every_row_becomes_a_record(self):
        self.assertEqual(len(self.records), 2)

    def test_mapped_fields_land_in_the_right_places(self):
        r = self.records[0]
        self.assertEqual(r.molecule.inchikey, "AAAAAAAAAAAAAA-BBBBBBBBBB-N")
        self.assertEqual(r.molecule.atom_count, 2)
        self.assertEqual(r.nucleus, "13C")
        self.assertEqual(r.source.record_id, "SYN-0001")
        self.assertEqual(r.source.licence, "CC BY 4.0")
        self.assertEqual(r.molecule.external_ids, {"native": "SYN-0001"})

    def test_a_transform_converts_units(self):
        self.assertEqual(self.records[0].conditions.temperature_k, 298.15)

    def test_shifts_are_parsed_with_atom_indices(self):
        shifts = self.records[0].shifts
        self.assertEqual([s.atom_index for s in shifts], [0, 1])
        self.assertEqual([s.shift_ppm for s in shifts], [10.5, 20.25])

    def test_spectrum_state_is_derived_from_what_actually_arrived(self):
        self.assertIs(self.records[0].spectrum_state, SpectrumState.ASSIGNED_PEAKS)
        self.assertIs(self.records[1].spectrum_state, SpectrumState.UNASSIGNED_PEAKS)

    def test_lineage_defaults_to_the_original_experiment(self):
        self.assertIs(self.records[0].source.lineage, Lineage.ORIGINAL_EXPERIMENT)


class TestAbsentFieldsStayUnknown(unittest.TestCase):
    """The whole point: a source that omits a field must not get a default."""

    def setUp(self):
        self.record = map_payload(_payload(), _plan())[1]

    def test_missing_conditions_are_unknown_not_defaulted(self):
        for f in ("solvent", "temperature_k", "reference_compound"):
            with self.subTest(f=f):
                self.assertIs(getattr(self.record.conditions, f), UNKNOWN)

    def test_missing_licence_is_unknown(self):
        self.assertFalse(is_known(self.record.source.licence))

    def test_missing_atom_index_leaves_the_peak_unassigned(self):
        self.assertFalse(self.record.has_any_assignment)

    def test_an_unparseable_number_is_dropped_not_coerced_to_zero(self):
        """'bad-value' must not silently become 0.0 ppm."""
        self.assertEqual([s.shift_ppm for s in self.record.shifts], [7.26])

    def test_the_record_reports_what_it_is_missing(self):
        missing = self.record.missing_metadata()
        for f in ("solvent", "temperature_k", "reference_compound",
                  "source.licence", "atom_assignments"):
            with self.subTest(f=f):
                self.assertIn(f, missing)


class TestUnconfirmedPlansRefuseLiveUse(unittest.TestCase):
    def test_fetch_is_refused_while_the_schema_is_unconfirmed(self):
        adapter = SourceAdapter(plan=_plan(), client=object())
        with self.assertRaises(SchemaUnconfirmed) as ctx:
            adapter.fetch("by_inchikey", inchikey="X")
        self.assertIn("no real response has been read", str(ctx.exception))

    def test_parsing_still_works_offline(self):
        adapter = SourceAdapter(plan=_plan())
        self.assertEqual(len(adapter.parse(_payload())), 2)

    def test_status_separates_documented_from_inferred_routes(self):
        status = SourceAdapter(plan=_plan()).status()
        self.assertFalse(status["schema_confirmed"])
        self.assertEqual(status["documented_route_count"], 0)
        self.assertEqual(status["inferred_route_count"], 1)

    def test_a_route_reports_its_missing_parameter(self):
        with self.assertRaises(AdapterError) as ctx:
            _plan().route("by_inchikey").render()
        self.assertIn("inchikey", str(ctx.exception))


class TestPlanLoading(unittest.TestCase):
    def test_a_plan_loads_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "nmrshiftdb2.json").write_text(json.dumps(PLAN))
            plan = AdapterPlan.load("nmrshiftdb2", tmp)
        self.assertEqual(plan.source_id, "nmrshiftdb2")
        self.assertFalse(plan.schema_confirmed)


if __name__ == "__main__":
    unittest.main()
