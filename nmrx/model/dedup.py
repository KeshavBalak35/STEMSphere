"""Collapse the same underlying experiment across aggregators -- without losing lineage.

The map warns about this repeatedly:

* "The same PDB ID served twice is one experiment, not two independent supporting results."
* MoNA/GNPS "may overlap MassBank; do not count mirrors as independent evidence."
* BindingDB imports ChEMBL records, so "deduplicate imported ChEMBL evidence."

The rule this module implements: **merge for counting, never for provenance.** A cluster
reports one experiment, and keeps every source that served it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .provenance import Lineage, unwrap
from .records import NMRRecord, SourceRef

#: Documented "this aggregator re-serves that source" relationships from the map.
#: A record from the key source that matches a record from the value source is a mirror,
#: not corroboration.
KNOWN_MIRROR_OF: Dict[str, Tuple[str, ...]] = {
    "mona": ("massbank", "gnps"),
    "gnps": ("massbank",),
    "bindingdb": ("chembl",),
    "pdbe": ("rcsb",),
    "rcsb": ("pdbe",),
    "nfdi4chem": ("chemotion", "massbank", "nmrxiv"),
    "fairsharing": (),
}

#: Preference order when picking a cluster's primary record. Earlier wins.
_PRIMARY_SOURCE_PREFERENCE = (
    "nmrshiftdb2", "bmrb", "nmrxiv", "chemotion", "massbank", "gnps", "mona",
    "chembl", "bindingdb", "rcsb", "pdbe", "pubchem",
)


def _shift_fingerprint(rec: NMRRecord, ndigits: int = 2) -> Tuple:
    """Rounded, order-independent shape of the spectrum.

    Rounded because two services reprocessing one acquisition legitimately differ in the
    last decimal; order-independent because peak ordering is not meaningful.
    """
    return tuple(sorted((s.element, round(s.shift_ppm, ndigits)) for s in rec.shifts))


def experiment_key(rec: NMRRecord, ndigits: int = 2) -> Tuple:
    """Identity of the underlying *experiment*, independent of who served it."""
    return (
        unwrap(rec.molecule.inchikey),
        unwrap(rec.nucleus),
        unwrap(rec.conditions.solvent),
        unwrap(rec.conditions.temperature_k),
        unwrap(rec.conditions.reference_compound),
        rec.evidence_class.value,
        _shift_fingerprint(rec, ndigits),
    )


@dataclass
class ExperimentCluster:
    """One underlying experiment plus every source that served it."""

    key: Tuple
    records: List[NMRRecord] = field(default_factory=list)

    @property
    def primary(self) -> NMRRecord:
        """The record NMRx quotes. Originals beat mirrors; then licence known; then preference."""
        def rank(r: NMRRecord) -> Tuple:
            return (
                0 if r.source.lineage is Lineage.ORIGINAL_EXPERIMENT else 1,
                0 if unwrap(r.source.licence) else 1,
                _PRIMARY_SOURCE_PREFERENCE.index(r.source.source_id)
                if r.source.source_id in _PRIMARY_SOURCE_PREFERENCE
                else len(_PRIMARY_SOURCE_PREFERENCE),
                0 if r.fully_assigned else 1,
            )
        return sorted(self.records, key=rank)[0]

    @property
    def source_refs(self) -> List[SourceRef]:
        """Every source that served this experiment. Never pruned."""
        return [r.source for r in self.records]

    @property
    def source_ids(self) -> List[str]:
        seen: List[str] = []
        for r in self.records:
            if r.source.source_id not in seen:
                seen.append(r.source.source_id)
        return seen

    def independent_support_count(self) -> int:
        """How many *genuinely independent* results back this experiment.

        A declared mirror, and a source documented as re-serving another source already in
        the cluster, both count as zero additional support.
        """
        counted: List[str] = []
        for r in self.records:
            sid = r.source.source_id
            if r.source.lineage is not Lineage.ORIGINAL_EXPERIMENT:
                continue
            if any(sid in KNOWN_MIRROR_OF.get(other, ()) or other in KNOWN_MIRROR_OF.get(sid, ())
                   for other in counted):
                continue
            if sid not in counted:
                counted.append(sid)
        return len(counted)

    def to_dict(self) -> dict:
        return {
            "primary": self.primary.to_dict(),
            "served_by": [s.to_dict() for s in self.source_refs],
            "source_ids": self.source_ids,
            "record_count": len(self.records),
            "independent_support_count": self.independent_support_count(),
        }


def cluster_records(records: Iterable[NMRRecord], ndigits: int = 2) -> List[ExperimentCluster]:
    """Group records by underlying experiment, preserving every source."""
    buckets: Dict[Tuple, ExperimentCluster] = {}
    for rec in records:
        key = experiment_key(rec, ndigits)
        cluster = buckets.get(key)
        if cluster is None:
            cluster = buckets[key] = ExperimentCluster(key=key)
        cluster.records.append(rec)
    return list(buckets.values())


def dedup_summary(clusters: Sequence[ExperimentCluster]) -> dict:
    """Counts a report can quote without overstating independence."""
    per_source = defaultdict(int)
    for c in clusters:
        for sid in c.source_ids:
            per_source[sid] += 1
    return {
        "distinct_experiments": len(clusters),
        "total_records": sum(len(c.records) for c in clusters),
        "clusters_with_multiple_sources": sum(1 for c in clusters if len(c.source_ids) > 1),
        "clusters_with_independent_support": sum(
            1 for c in clusters if c.independent_support_count() > 1
        ),
        "records_per_source": dict(sorted(per_source.items())),
    }
