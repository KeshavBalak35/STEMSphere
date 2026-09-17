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

from .provenance import UNKNOWN, Lineage, unwrap
from .records import NMRRecord, SourceRef

#: Documented "this aggregator re-serves that source" relationships.
#:
#: Loaded from the registry's ``republishes`` / ``overlaps_with`` fields rather than hardcoded,
#: so the lineage lives as data next to the evidence for it. The literal below is only the
#: fallback used when the registry cannot be read (e.g. in an isolated unit test).
_FALLBACK_MIRROR_OF: Dict[str, Tuple[str, ...]] = {
    "mona": ("massbank", "gnps"),
    "gnps": ("massbank",),
    "bindingdb": ("chembl",),
    "pdbe": ("rcsb",),
    "rcsb": ("pdbe",),
    "nfdi4chem": ("chemotion", "massbank", "nmrxiv"),
}


def _load_mirror_map() -> Dict[str, Tuple[str, ...]]:
    try:
        from ..sources.registry import load_registry

        registry = load_registry()
    except Exception:  # noqa: BLE001 -- dedup must work without the registry file
        return dict(_FALLBACK_MIRROR_OF)

    out: Dict[str, Tuple[str, ...]] = {}
    for source in registry:
        related = set(source.republishes) | set(source.overlaps_with)
        if related:
            out[source.id] = tuple(sorted(related))
    return out or dict(_FALLBACK_MIRROR_OF)


#: source_id -> the sources it is documented to share underlying records with.
KNOWN_MIRROR_OF: Dict[str, Tuple[str, ...]] = _load_mirror_map()

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
    """Identity of the underlying *experiment*, independent of who served it.

    A record whose molecule is not pinned by an InChIKey cannot be matched to anything: two
    unidentified records with no shifts would otherwise share an all-UNKNOWN key and merge
    into a single "experiment" despite being different molecules. Such a record gets a key
    unique to itself, so it clusters alone and never absorbs another.
    """
    if unwrap(rec.molecule.inchikey) is UNKNOWN:
        return (
            "__unidentified__",
            rec.source.source_id,
            unwrap(rec.source.record_id),
            id(rec) if unwrap(rec.source.record_id) is UNKNOWN else None,
        )
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

        Counts connected components of the documented overlap graph, not sources. Counting
        pairwise against an already-counted list undercounts the suppression: if MoNA and
        GNPS both re-serve MassBank and MassBank itself is absent from the cluster, neither
        is a mirror *of the other* in the list, so both would count and one experiment would
        read as two corroborating results.
        """
        sources = [
            r.source.source_id for r in self.records
            if r.source.lineage is Lineage.ORIGINAL_EXPERIMENT
        ]
        # Declared mirrors add nothing, whatever their source.
        unique: List[str] = []
        for sid in sources:
            if sid not in unique:
                unique.append(sid)

        # Union-find over the documented overlap relation, including shared upstreams.
        parent = {sid: sid for sid in unique}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for a in unique:
            related_a = set(KNOWN_MIRROR_OF.get(a, ()))
            for b in unique:
                if a == b:
                    continue
                related_b = set(KNOWN_MIRROR_OF.get(b, ()))
                # directly related, or both documented as re-serving a common upstream
                if b in related_a or a in related_b or (related_a & related_b):
                    union(a, b)

        return len({find(sid) for sid in unique})

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
