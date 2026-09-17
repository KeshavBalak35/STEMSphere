"""Merge for counting, never for provenance."""

import unittest

from nmrx.model.dedup import cluster_records, dedup_summary, experiment_key
from nmrx.model.provenance import Lineage
from nmrx.model.records import (
    ExperimentalConditions,
    MoleculeIdentity,
    NMRRecord,
    ShiftAssignment,
    SourceRef,
)

KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
CONDITIONS = ExperimentalConditions(solvent="CDCl3", temperature_k=298.0, reference_compound="TMS")
SHIFTS = [ShiftAssignment(0, "C", 170.12), ShiftAssignment(1, "C", 120.34)]


def rec(source_id, *, lineage=Lineage.ORIGINAL_EXPERIMENT, original=None,
        licence="CC BY 4.0", shifts=None):
    return NMRRecord(
        molecule=MoleculeIdentity(inchikey=KEY, atom_count=2),
        source=SourceRef(source_id=source_id, record_id=f"{source_id}-1", licence=licence,
                         lineage=lineage, original_source_id=original),
        nucleus="13C",
        conditions=CONDITIONS,
        shifts=list(shifts if shifts is not None else SHIFTS),
    )


class TestClustering(unittest.TestCase):
    def test_the_same_experiment_from_three_services_is_one_experiment(self):
        clusters = cluster_records([
            rec("massbank"),
            rec("mona", lineage=Lineage.MIRRORED_COPY, original="massbank"),
            rec("gnps", lineage=Lineage.MIRRORED_COPY, original="massbank"),
        ])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].independent_support_count(), 1)

    def test_no_source_is_ever_dropped(self):
        clusters = cluster_records([
            rec("massbank"),
            rec("mona", lineage=Lineage.MIRRORED_COPY, original="massbank"),
        ])
        self.assertEqual(clusters[0].source_ids, ["massbank", "mona"])
        self.assertEqual(len(clusters[0].source_refs), 2)

    def test_genuinely_separate_measurements_stay_separate(self):
        other = [ShiftAssignment(0, "C", 55.0), ShiftAssignment(1, "C", 30.0)]
        clusters = cluster_records([rec("nmrshiftdb2"), rec("bmrb", shifts=other)])
        self.assertEqual(len(clusters), 2)

    def test_two_independent_labs_do_corroborate(self):
        clusters = cluster_records([rec("nmrshiftdb2"), rec("bmrb")])
        self.assertEqual(clusters[0].independent_support_count(), 2)

    def test_documented_aggregator_overlap_is_not_corroboration(self):
        """BindingDB imports ChEMBL; two rows are one result."""
        clusters = cluster_records([rec("chembl"), rec("bindingdb")])
        self.assertEqual(clusters[0].independent_support_count(), 1)

    def test_pdbe_and_rcsb_share_one_archive(self):
        clusters = cluster_records([rec("rcsb"), rec("pdbe")])
        self.assertEqual(clusters[0].independent_support_count(), 1)

    def test_minor_rounding_differences_still_cluster(self):
        a = rec("massbank")
        b = rec("mona", lineage=Lineage.MIRRORED_COPY, original="massbank",
                shifts=[ShiftAssignment(0, "C", 170.119), ShiftAssignment(1, "C", 120.344)])
        self.assertEqual(len(cluster_records([a, b])), 1)

    def test_peak_order_does_not_create_a_second_experiment(self):
        reversed_shifts = list(reversed(SHIFTS))
        self.assertEqual(experiment_key(rec("a")), experiment_key(rec("b", shifts=reversed_shifts)))


class TestPrimarySelection(unittest.TestCase):
    def test_an_original_beats_a_mirror(self):
        clusters = cluster_records([
            rec("mona", lineage=Lineage.MIRRORED_COPY, original="massbank"),
            rec("massbank"),
        ])
        self.assertEqual(clusters[0].primary.source.source_id, "massbank")

    def test_a_licensed_record_beats_an_unlicensed_one(self):
        clusters = cluster_records([rec("gnps", licence=None), rec("massbank", licence="CC BY 4.0")])
        self.assertEqual(clusters[0].primary.source.source_id, "massbank")


class TestSummary(unittest.TestCase):
    def test_summary_does_not_overstate_independence(self):
        summary = dedup_summary(cluster_records([
            rec("massbank"),
            rec("mona", lineage=Lineage.MIRRORED_COPY, original="massbank"),
        ]))
        self.assertEqual(summary["distinct_experiments"], 1)
        self.assertEqual(summary["total_records"], 2)
        self.assertEqual(summary["clusters_with_independent_support"], 0)

    def test_per_source_counts_are_preserved(self):
        summary = dedup_summary(cluster_records([rec("massbank"), rec("nmrshiftdb2")]))
        self.assertEqual(summary["records_per_source"], {"massbank": 1, "nmrshiftdb2": 1})


if __name__ == "__main__":
    unittest.main()
