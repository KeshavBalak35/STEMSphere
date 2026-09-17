"""NMRx source-discovery and NMR data layer.

Subpackages:

``nmrx.sources``
    the registry of candidate databases, the access policy that decides what NMRx may
    actually call, a byte-capped HTTP client and the pilot connectivity probe.
``nmrx.model``
    provenance vocabulary, NMR record types, the strict calibration gate and
    cross-aggregator deduplication.
``nmrx.adapters``
    declarative per-source plans (routes + field mapping) and the mapping engine.
``nmrx.reports``
    coverage and missingness reporting.

Two invariants hold across the whole package:

1. **The registry grants nothing.** Only ``nmrx/data/access_policy.json`` grants, and the
   cloud environment's own network settings can still refuse.
2. **Unknown stays unknown.** No missing solvent, temperature, reference or licence is ever
   filled in with a default; recovered values carry their derivation.
"""

__version__ = "0.1.0"

__all__ = ["sources", "model", "adapters", "reports"]
