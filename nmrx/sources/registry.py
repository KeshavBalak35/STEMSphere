"""Loader and query layer for the NMRx source registry.

The registry is a *research directory*: 50 candidate databases, datasets and discovery
services with their documented hosts, access routes, rights evidence and NMR relevance.

Two things it deliberately is not:

* it is not a permission grant -- see :mod:`nmrx.sources.policy`;
* it is not proof that any record is retrievable, complete or licensed for reuse.
  ``rights.status`` records what provider documentation *says*, and carries an explicit
  ``unverified`` state for the sources whose licence text could not be read.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "source_registry.json"

#: Connection status of a source inside NMRx. Ordered weakest to strongest.
STATUS_VALUES = ("unimplemented", "documented_only", "blocked", "fixture_tested", "live_tested")

TIER_VALUES = (
    "pilot",
    "nmr_expansion",
    "next_connection",
    "later_extension",
    "specialist",
    "discovery",
    "restricted",
)

RIGHTS_STATUS_VALUES = (
    "open_verified",
    "open_unverified",
    "per_record",
    "non_commercial",
    "licensed_required",
    "unverified",
)

HARVEST_POLICY_VALUES = (
    "allowed_when_unblocked",
    "manual_only",
    "prohibited",
    "licence_required",
)

VERDICT_VALUES = ("yes", "partial", "no", "unknown")


class RegistryError(ValueError):
    """Raised when the registry file violates its own contract."""


@dataclass(frozen=True)
class Source:
    """One registry entry. Thin wrapper -- the JSON stays the source of truth."""

    raw: dict

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def number(self) -> int:
        return self.raw["number"]

    @property
    def name(self) -> str:
        return self.raw["name"]

    @property
    def tier(self) -> str:
        return self.raw["nmrx_tier"]

    @property
    def status(self) -> str:
        return self.raw["status"]

    @property
    def data_types(self) -> List[str]:
        return list(self.raw.get("data_types", []))

    @property
    def evidence_types(self) -> List[str]:
        return list(self.raw.get("evidence_types", []))

    @property
    def rights_status(self) -> str:
        return self.raw["rights"]["status"]

    @property
    def commercial_use(self) -> str:
        return self.raw["rights"].get("commercial_use", "unknown")

    @property
    def harvest_policy(self) -> str:
        return self.raw["harvest_policy"]

    @property
    def has_nmr(self) -> bool:
        return bool(self.raw.get("nmr_relevance", {}).get("has_nmr", False))

    @property
    def assignments(self) -> str:
        return self.raw.get("nmr_relevance", {}).get("assignments", "unknown")

    @property
    def conditions(self) -> str:
        return self.raw.get("nmr_relevance", {}).get("conditions", "unknown")

    def hosts(self, role: Optional[str] = None) -> List[str]:
        """Hostnames for one role (``api``/``web``/``files``/``docs``) or all roles."""
        h = self.raw.get("hosts", {})
        roles: Iterable[str] = [role] if role else h.keys()
        out: List[str] = []
        for r in roles:
            for pair in h.get(r, []) or []:
                out.append(pair[0] if isinstance(pair, (list, tuple)) else pair)
        return out

    def routes(self) -> List[dict]:
        return list(self.raw.get("access", {}).get("routes", []) or [])

    def documented_routes(self) -> List[dict]:
        return [r for r in self.routes() if r.get("provenance") == "documented"]

    def needs_credentials(self) -> bool:
        return self.raw.get("access", {}).get("auth", "unknown") in ("api_key", "account", "license")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Source {self.id} tier={self.tier} status={self.status}>"


class SourceRegistry:
    """Queryable view over the registry file."""

    def __init__(self, entries: Sequence[dict], meta: Optional[dict] = None) -> None:
        self._sources = [Source(e) for e in entries]
        self._by_id: Dict[str, Source] = {}
        for s in self._sources:
            if s.id in self._by_id:
                raise RegistryError(f"duplicate source id {s.id!r}")
            self._by_id[s.id] = s
        self.meta = dict(meta or {})

    # -- construction --------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str = REGISTRY_PATH) -> "SourceRegistry":
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, list):
            return cls(doc)
        entries = doc.get("sources")
        if entries is None:
            raise RegistryError("registry document has no 'sources' key")
        meta = {k: v for k, v in doc.items() if k != "sources"}
        return cls(entries, meta)

    # -- access --------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._sources)

    def __iter__(self):
        return iter(self._sources)

    def __getitem__(self, source_id: str) -> Source:
        try:
            return self._by_id[source_id]
        except KeyError:
            raise KeyError(f"no source with id {source_id!r}") from None

    def get(self, source_id: str) -> Optional[Source]:
        return self._by_id.get(source_id)

    def ids(self) -> List[str]:
        return [s.id for s in self._sources]

    def by_tier(self, *tiers: str) -> List[Source]:
        want = set(tiers)
        return [s for s in self._sources if s.tier in want]

    def by_status(self, *statuses: str) -> List[Source]:
        want = set(statuses)
        return [s for s in self._sources if s.status in want]

    def with_data_type(self, data_type: str) -> List[Source]:
        return [s for s in self._sources if data_type in s.data_types]

    def nmr_sources(self) -> List[Source]:
        return [s for s in self._sources if s.has_nmr]

    def measured_nmr_sources(self) -> List[Source]:
        """Sources that carry NMR *and* claim measured evidence -- the NMRx priority set."""
        return [s for s in self.nmr_sources() if "measured" in s.evidence_types]

    def harvestable(self) -> List[Source]:
        """Sources whose harvest policy permits automation once the network is open."""
        return [s for s in self._sources if s.harvest_policy == "allowed_when_unblocked"]

    def all_hosts(self, role: Optional[str] = None) -> List[str]:
        seen: List[str] = []
        for s in self._sources:
            for h in s.hosts(role):
                if h not in seen:
                    seen.append(h)
        return sorted(seen)

    # -- integrity -----------------------------------------------------------

    def validate(self) -> List[str]:
        """Return a list of contract violations. Empty list means the registry is sound."""
        problems: List[str] = []
        for s in self._sources:
            e = s.raw
            where = f"{s.id}"
            for key in ("id", "number", "name", "group", "nmrx_tier", "status",
                        "data_types", "evidence_types", "hosts", "access", "rights",
                        "nmr_relevance", "harvest_policy", "automated_ingestion_approved"):
                if key not in e:
                    problems.append(f"{where}: missing required key {key!r}")
            if e.get("nmrx_tier") not in TIER_VALUES:
                problems.append(f"{where}: nmrx_tier {e.get('nmrx_tier')!r} not in {TIER_VALUES}")
            if e.get("status") not in STATUS_VALUES:
                problems.append(f"{where}: status {e.get('status')!r} not in {STATUS_VALUES}")
            if e.get("harvest_policy") not in HARVEST_POLICY_VALUES:
                problems.append(f"{where}: harvest_policy {e.get('harvest_policy')!r} invalid")
            if e.get("automated_ingestion_approved") is not False:
                problems.append(
                    f"{where}: automated_ingestion_approved must stay False -- the source map "
                    "grants no ingestion permission"
                )
            rights = e.get("rights", {})
            if rights.get("status") not in RIGHTS_STATUS_VALUES:
                problems.append(f"{where}: rights.status {rights.get('status')!r} invalid")
            if rights.get("commercial_use") not in ("yes", "no", "unknown", "negotiate"):
                problems.append(f"{where}: rights.commercial_use {rights.get('commercial_use')!r} invalid")
            nmr = e.get("nmr_relevance", {})
            for k in ("assignments", "conditions"):
                if nmr.get(k) not in VERDICT_VALUES:
                    problems.append(f"{where}: nmr_relevance.{k} {nmr.get(k)!r} invalid")
            hosts = e.get("hosts", {})
            if not isinstance(hosts, dict):
                problems.append(f"{where}: hosts must be an object keyed by role")
            else:
                for role in hosts:
                    if role not in ("api", "web", "files", "docs"):
                        problems.append(f"{where}: unknown host role {role!r}")
            for route in e.get("access", {}).get("routes", []) or []:
                if route.get("provenance") not in ("documented", "inferred"):
                    problems.append(
                        f"{where}: route {route.get('url')!r} has provenance "
                        f"{route.get('provenance')!r}; must be 'documented' or 'inferred'"
                    )
        return problems

    # -- summary -------------------------------------------------------------

    def summary(self) -> dict:
        return {
            "source_count": len(self._sources),
            "by_tier": dict(Counter(s.tier for s in self._sources)),
            "by_status": dict(Counter(s.status for s in self._sources)),
            "by_rights_status": dict(Counter(s.rights_status for s in self._sources)),
            "by_harvest_policy": dict(Counter(s.harvest_policy for s in self._sources)),
            "nmr_sources": len(self.nmr_sources()),
            "measured_nmr_sources": len(self.measured_nmr_sources()),
            "with_assignments_yes": sum(1 for s in self.nmr_sources() if s.assignments == "yes"),
            "with_conditions_yes": sum(1 for s in self.nmr_sources() if s.conditions == "yes"),
        }


def load_registry(path: Path | str = REGISTRY_PATH) -> SourceRegistry:
    return SourceRegistry.load(path)
