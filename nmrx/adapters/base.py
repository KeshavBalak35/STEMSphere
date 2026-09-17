"""Declarative source adapters.

We cannot reach any chemistry host from this environment, so no live API schema has been
confirmed. Writing hand-rolled parsers against *guessed* response shapes would bake guesses
into code and make them look verified. This module takes a different approach:

* an adapter is a **plan** (:class:`AdapterPlan`) -- routes plus a field mapping -- stored as
  JSON alongside a ``schema_confirmed`` flag;
* a single generic :func:`map_payload` engine turns any payload into an
  :class:`~nmrx.model.records.NMRRecord` by following that mapping;
* when someone finally reads the real API response, they edit the mapping JSON. No new
  parser code, and the ``schema_confirmed`` flag is the one place that records whether a
  human has actually seen a real response.

An adapter whose plan is unconfirmed refuses to report itself as live-capable. It can still
be exercised end to end against fixtures, which is what ``status: fixture_tested`` means in
the registry.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ..model.provenance import (
    UNKNOWN,
    EvidenceClass,
    IdentityMatch,
    Lineage,
    SpectrumState,
)
from ..model.records import (
    ExperimentalConditions,
    MoleculeIdentity,
    NMRRecord,
    ShiftAssignment,
    SourceRef,
)

MAPPINGS_DIR = Path(__file__).resolve().parent / "mappings"


class AdapterError(Exception):
    pass


class SchemaUnconfirmed(AdapterError):
    """Raised when live use is attempted against a plan nobody has verified."""


# --- path access -------------------------------------------------------------

def get_path(payload: Any, path: str, default: Any = UNKNOWN) -> Any:
    """Read a dotted path out of nested dicts/lists.

    ``"a.b[0].c"`` walks dicts by key and lists by index. A missing step yields ``default``
    (UNKNOWN by default) rather than raising -- a source omitting a field is expected, and
    must surface as unknown rather than as an error or a substituted value.
    """
    if not path:
        return default
    cur = payload
    for raw in path.split("."):
        key, _, rest = raw.partition("[")
        if key:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return default
        while rest:
            if "]" not in rest:
                return default          # unterminated index -- a typo, not a path
            idx_s, _, rest = rest.partition("]")
            rest = rest.lstrip("[")
            try:
                idx = int(idx_s)
            except ValueError:
                return default
            if isinstance(cur, (list, tuple)) and -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return default
    return cur


#: Value transforms a mapping may name. Kept tiny and total -- a transform that cannot
#: produce a sensible value returns UNKNOWN rather than guessing.
def _to_float(v: Any) -> Any:
    """Total: anything that is not a finite real number yields UNKNOWN.

    NaN and infinity parse happily as floats and would be stored as chemical shifts, where
    they silently poison every downstream average, comparison and export.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return UNKNOWN
    return f if math.isfinite(f) else UNKNOWN


def _to_int(v: Any) -> Any:
    try:
        return int(v)
    except (TypeError, ValueError):
        return UNKNOWN


def _celsius_to_kelvin(v: Any) -> Any:
    f = _to_float(v)
    return UNKNOWN if f is UNKNOWN else round(f + 273.15, 2)


def _strip(v: Any) -> Any:
    return v.strip() if isinstance(v, str) and v.strip() else (UNKNOWN if isinstance(v, str) else v)

TRANSFORMS: Dict[str, Callable[[Any], Any]] = {
    "float": _to_float,
    "int": _to_int,
    "str": lambda v: str(v) if v is not UNKNOWN and v is not None else UNKNOWN,
    "strip": _strip,
    "celsius_to_kelvin": _celsius_to_kelvin,
    "identity": lambda v: v,
}


def _apply(value: Any, spec: dict) -> Any:
    if value is UNKNOWN or value is None:
        return UNKNOWN
    name = spec.get("transform", "identity")
    fn = TRANSFORMS.get(name)
    if fn is None:
        raise AdapterError(f"unknown transform {name!r}")
    out = fn(value)
    mapping = spec.get("value_map")
    if mapping and isinstance(out, str):
        out = mapping.get(out, mapping.get("*", out))
    return out


def _field(payload: Any, spec: Optional[dict]) -> Any:
    """Resolve one mapped field. A spec with no ``path`` yields its ``const``, else UNKNOWN.

    There is deliberately **no ``default``**. A mapping that could substitute a value when the
    source omitted a field would let a missing licence become "CC0" or a missing solvent
    become "CDCl3" -- exactly the fabrication the whole package exists to prevent. An absent
    path yields UNKNOWN, always. ``const`` is for values that genuinely do not come from the
    payload (a fixed licence for a single-licence source), and is rejected alongside a path so
    it cannot act as a fallback.
    """
    if not spec:
        return UNKNOWN
    if "default" in spec:
        raise AdapterError(
            "mapping field declares a 'default'; defaults are forbidden because they turn a "
            "field the source omitted into a value it never stated. Use 'const' for a value "
            "that genuinely does not come from the payload."
        )
    if "const" in spec:
        if "path" in spec:
            raise AdapterError("mapping field declares both 'const' and 'path'; pick one")
        return spec["const"]
    return _apply(get_path(payload, spec.get("path", "")), spec)


# --- the plan ----------------------------------------------------------------

@dataclass(frozen=True)
class Route:
    purpose: str
    url_template: str
    provenance: str            # "documented" | "inferred"
    doc_link: str = ""
    response_format: str = "unknown"
    must_confirm_live: str = ""

    @property
    def is_documented(self) -> bool:
        return self.provenance == "documented"

    def render(self, **params: Any) -> str:
        try:
            return self.url_template.format(**params)
        except KeyError as exc:
            raise AdapterError(
                f"route {self.purpose!r} needs parameter {exc.args[0]!r}"
            ) from None


@dataclass
class AdapterPlan:
    """Everything an adapter knows, loaded from JSON."""

    source_id: str
    name: str
    schema_confirmed: bool
    hosts_required: List[str] = field(default_factory=list)
    routes: List[Route] = field(default_factory=list)
    record_mapping: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, str] = field(default_factory=dict)
    blocking_unknowns: List[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "AdapterPlan":
        return cls(
            source_id=d["source_id"],
            name=d.get("name", d["source_id"]),
            schema_confirmed=bool(d.get("schema_confirmed", False)),
            hosts_required=list(d.get("hosts_required", [])),
            routes=[Route(**r) for r in d.get("routes", [])],
            # Deep copy: record_mapping is nested, so a shallow dict() would leave the
            # plan sharing inner dicts with the caller's document. Editing a loaded plan
            # would then mutate whatever it was loaded from.
            record_mapping=deepcopy(d.get("record_mapping", {})),
            capabilities=dict(d.get("capabilities", {})),
            blocking_unknowns=list(d.get("blocking_unknowns", [])),
            notes=d.get("notes", ""),
        )

    @classmethod
    def load(cls, source_id: str, directory: Path | str = MAPPINGS_DIR) -> "AdapterPlan":
        path = Path(directory) / f"{source_id}.json"
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def route(self, purpose: str) -> Route:
        for r in self.routes:
            if r.purpose == purpose:
                return r
        raise AdapterError(f"{self.source_id}: no route named {purpose!r}")


# --- mapping engine ----------------------------------------------------------

def map_payload(payload: Any, plan: AdapterPlan, *, retrieved_at: Any = UNKNOWN) -> List[NMRRecord]:
    """Turn a source payload into NMRRecords using the plan's declarative mapping.

    Unmapped and absent fields become UNKNOWN. Nothing is defaulted into existence.
    """
    m = plan.record_mapping
    if not m:
        raise AdapterError(f"{plan.source_id}: plan has no record_mapping")

    root_path = m.get("records_path", "")
    rows = get_path(payload, root_path) if root_path else payload
    if rows is UNKNOWN:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return []

    out: List[NMRRecord] = []
    for row in rows:
        out.append(_map_one(row, plan, retrieved_at))
    return out


def _map_one(row: Any, plan: AdapterPlan, retrieved_at: Any) -> NMRRecord:
    m = plan.record_mapping
    mol_spec = m.get("molecule", {})
    molecule = MoleculeIdentity(
        inchikey=_field(row, mol_spec.get("inchikey")),
        inchi=_field(row, mol_spec.get("inchi")),
        smiles=_field(row, mol_spec.get("smiles")),
        formula=_field(row, mol_spec.get("formula")),
        net_charge=_field(row, mol_spec.get("net_charge")),
        atom_count=_field(row, mol_spec.get("atom_count")),
        name=_field(row, mol_spec.get("name")),
        external_ids=_external_ids(row, mol_spec.get("external_ids", {})),
    )

    src_spec = m.get("source", {})
    lineage = Lineage(_enum_value(_field(row, src_spec.get("lineage")),
                                  Lineage, Lineage.UNKNOWN))
    original = _field(row, src_spec.get("original_source_id"))
    source = SourceRef(
        source_id=plan.source_id,
        record_id=_field(row, src_spec.get("record_id")),
        url=_field(row, src_spec.get("url")),
        retrieved_at=retrieved_at,
        licence=_field(row, src_spec.get("licence")),
        lineage=lineage,
        original_source_id=None if original is UNKNOWN else original,
    )

    cond_spec = m.get("conditions", {})
    conditions = ExperimentalConditions(
        solvent=_field(row, cond_spec.get("solvent")),
        temperature_k=_field(row, cond_spec.get("temperature_k")),
        reference_compound=_field(row, cond_spec.get("reference_compound")),
        spectrometer_frequency_mhz=_field(row, cond_spec.get("spectrometer_frequency_mhz")),
        ph=_field(row, cond_spec.get("ph")),
        pulse_sequence=_field(row, cond_spec.get("pulse_sequence")),
    )

    shifts = _map_shifts(row, m.get("shifts", {}))

    evidence = EvidenceClass(_enum_value(_field(row, m.get("evidence_class")),
                                         EvidenceClass, EvidenceClass.UNKNOWN))
    state_raw = _field(row, m.get("spectrum_state"))
    if state_raw is UNKNOWN:
        # Derive honestly from what actually arrived rather than assuming.
        if not shifts:
            state = SpectrumState.RAW
        elif all(s.is_assigned for s in shifts):
            state = SpectrumState.ASSIGNED_PEAKS
        else:
            state = SpectrumState.UNASSIGNED_PEAKS
    else:
        state = SpectrumState(_enum_value(state_raw, SpectrumState,
                                          SpectrumState.UNASSIGNED_PEAKS))

    return NMRRecord(
        molecule=molecule,
        source=source,
        nucleus=_field(row, m.get("nucleus")),
        evidence_class=evidence,
        spectrum_state=state,
        identity_match=IdentityMatch(_enum_value(_field(row, m.get("identity_match")),
                                                 IdentityMatch,
                                                 IdentityMatch.UNKNOWN_RELATION)),
        conditions=conditions,
        shifts=shifts,
        raw_file_urls=_string_list(row, m.get("raw_file_urls")),
        notes=[plan.notes] if plan.notes else [],
    )


def _map_shifts(row: Any, spec: dict) -> List[ShiftAssignment]:
    if not spec:
        return []
    rows = get_path(row, spec.get("path", ""))
    if rows is UNKNOWN or not isinstance(rows, list):
        return []
    out: List[ShiftAssignment] = []
    for r in rows:
        # Route every conversion through the total transforms. Calling int()/float() here
        # directly would raise on a value the transforms are specified to turn into UNKNOWN.
        value = _to_float(_field(r, spec.get("shift_ppm")))
        if value is UNKNOWN:
            continue                      # a peak with no usable number is not a shift
        idx = _to_int(_field(r, spec.get("atom_index")))
        element = _field(r, spec.get("element"))
        out.append(ShiftAssignment(
            atom_index=None if idx is UNKNOWN else idx,
            element="?" if element is UNKNOWN else str(element),
            shift_ppm=value,
            multiplicity=_field(r, spec.get("multiplicity")),
            intensity=_field(r, spec.get("intensity")),
        ))
    return out


def _external_ids(row: Any, spec: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for label, s in (spec or {}).items():
        v = _field(row, s)
        if v is not UNKNOWN and v is not None:
            out[label] = str(v)
    return out


def _string_list(row: Any, spec: Optional[dict]) -> List[str]:
    v = _field(row, spec)
    if v is UNKNOWN or v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v if isinstance(x, (str, int, float))]
    return []


def _enum_value(raw: Any, enum_cls, default):
    if raw is UNKNOWN or raw is None:
        return default.value
    try:
        return enum_cls(raw).value
    except ValueError:
        return default.value


# --- the adapter -------------------------------------------------------------

@dataclass
class SourceAdapter:
    """Binds a plan to a transport. Fixture mode needs no network at all."""

    plan: AdapterPlan
    client: Optional[Any] = None      # BoundedHttpClient; None means fixture-only

    @classmethod
    def load(cls, source_id: str, client: Optional[Any] = None,
             directory: Path | str = MAPPINGS_DIR) -> "SourceAdapter":
        return cls(plan=AdapterPlan.load(source_id, directory), client=client)

    @property
    def source_id(self) -> str:
        return self.plan.source_id

    @property
    def hosts_required(self) -> List[str]:
        return list(self.plan.hosts_required)

    def parse(self, payload: Any, *, retrieved_at: Any = UNKNOWN) -> List[NMRRecord]:
        """Map a payload to records. Works offline; this is what fixture tests exercise."""
        return map_payload(payload, self.plan, retrieved_at=retrieved_at)

    def fetch(self, purpose: str, **params: Any):
        """Live fetch. Refuses while the plan's schema is unconfirmed."""
        if not self.plan.schema_confirmed:
            raise SchemaUnconfirmed(
                f"{self.source_id}: route schemas have not been confirmed against a real "
                f"response. Outstanding: {'; '.join(self.plan.blocking_unknowns) or 'unspecified'}. "
                "Confirm the documented schema, update the mapping JSON and set "
                "schema_confirmed=true before live use."
            )
        if self.client is None:
            raise AdapterError(f"{self.source_id}: no HTTP client bound")
        route = self.plan.route(purpose)
        url = route.render(**params)
        return self.client.get(url, source_id=self.source_id, purpose=route.purpose)

    def status(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.plan.name,
            "schema_confirmed": self.plan.schema_confirmed,
            "hosts_required": self.hosts_required,
            "routes": [
                {"purpose": r.purpose, "provenance": r.provenance, "url_template": r.url_template}
                for r in self.plan.routes
            ],
            "documented_route_count": sum(1 for r in self.plan.routes if r.is_documented),
            "inferred_route_count": sum(1 for r in self.plan.routes if not r.is_documented),
            "capabilities": dict(self.plan.capabilities),
            "blocking_unknowns": list(self.plan.blocking_unknowns),
        }


def available_plans(directory: Path | str = MAPPINGS_DIR) -> List[str]:
    d = Path(directory)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
