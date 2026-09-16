# Phase 0 report: what is actually here

Written after inspecting and running the code, not after reading its documentation.

## Source of truth

| Item | Value |
|---|---|
| Working copy | `nmrx2/` inside the STEMSphere repository |
| Commit | `d8033ec` |
| Branch | `claude/new-session-ltfg9j` |
| Uploaded ZIP | byte-identical to the working copy; only build caches differ (`__pycache__`, `.pytest_cache`, `.egg-info`) |

**Correction to the data-access document.** That document says the ZIP "predates the
calibration and harvesting work" and instructs Claude to go and find branch
`claude/new-session-ltfg9j`. That is out of date. The ZIP *is* that branch. The
calibration and harvest code is present, and the tests for it pass. No branch
recovery is needed and none was attempted.

## Baseline test run

```
cd nmrx2 && OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest -q
67 passed, 2 skipped, 2 warnings in 25.34s
```

Both skips are honest, not hidden failures:

| Skipped | Reason |
|---|---|
| `test_integration.py::test_worker_real_job` | `vina` is not installed, so docking cannot run |
| `test_cascade.py::test_real_corpus_calibrates_and_covers` | needs `NMRX_CASCADE_CACHE` pointing at a real download |

Installed and exercised: fastapi 0.141.1, pydantic 2.13.5, numpy 2.4.6, scipy 1.17.1,
rdkit 2026.3.6, pyscf 2.14.0, geomeTRIC 1.1.1, pyscf-properties 0.1.0, httpx 0.28.1,
pytest 9.1.1 on Python 3.11.15. `vina` absent.

## What exists and works

| Capability | Module | Verified by |
|---|---|---|
| Molecule preparation, valence and domain checks | `nmrx/chemistry.py` | 9 tests |
| Quantum orbitals, HOMO/LUMO, IR, GIAO NMR | `nmrx/quantum.py` | 4 tests, real PySCF runs |
| Vina docking | `nmrx/docking.py` | skipped, vina absent |
| SQLite job queue, worker, child-process isolation | `nmrx/store.py`, `worker.py`, `runner.py` | 3 tests |
| Conformal calibration, abstention, identity verdicts | `nmrx/calibration.py` | 22 tests |
| Size-conditional coverage | `nmrx/calibration.py` | measured 0.917 to 0.945 on the worst bucket |
| Public-source registry with licence status | `nmrx/harvest/sources.py` | 20 tests |
| NMRShiftDB SD-file parser | `nmrx/harvest/nmrshiftdb.py` | 20 tests |
| CASCADE dataset adapter | `nmrx/harvest/cascade.py` | 7 tests |
| 10 HTTP endpoints | `nmrx/api.py` | contract tests |

## What is genuinely missing

The data-access document is right about all of these. None of them exist:

1. No searchable molecular catalog. There is no table of molecules; the job queue
   stores jobs, not chemistry.
2. No provider connectors. `harvest/` reads files that are already on disk. Nothing
   talks to PubChem, nmrshiftdb2, ChEMBL, RCSB PDB or BindingDB.
3. No schema for spectra, assays, proteins, citations or licences as first-class
   records. Provenance currently rides along inside job result blobs.
4. No ingestion-run concept: no checkpoints, no resumability, no idempotent upserts,
   no deduplication, no rejection log.
5. No controlled import path for files from the user's computer.
6. No molecule dossier endpoint combining calculated and experimental evidence.
7. No source-policy manifest that can disable a connector at runtime.

## Network status: all five approved sources are blocked

One read-only probe per provider, run from this environment:

| Provider | Endpoint | Result |
|---|---|---|
| PubChem | `pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/property/MolecularFormula/TXT` | refused |
| nmrshiftdb2 | `nmrshiftdb.nmr.uni-koeln.de/` | refused |
| ChEMBL | `www.ebi.ac.uk/chembl/api/data/status.json` | refused |
| RCSB PDB | `data.rcsb.org/rest/v1/core/entry/1CBS` | refused |
| BindingDB | `www.bindingdb.org/rwd/bind/BindingDBRESTfulAPI.jsp` | refused |

The connection is refused by the environment's network policy before any request is
sent, so this is not a rate limit, an outage or a credential problem. Only code hosts
and package registries are reachable here.

This is the case the data-access document anticipated. Per its own instruction, the
response is **not** to find a scraping workaround. It is to build the provider
interfaces, contract tests against checked-in fixtures, import formats, source policy
and operator commands, so that the pipeline runs later on an approved machine with no
code change beyond enabling the allowlist.

## Domains that need network approval

Exact hosts, so an allowlist can be written without guesswork.

| Provider | Host | Access mode |
|---|---|---|
| PubChem | `pubchem.ncbi.nlm.nih.gov` | REST, 5 requests/second published limit |
| PubChem bulk | `ftp.ncbi.nlm.nih.gov` | bulk download |
| nmrshiftdb2 | `nmrshiftdb.nmr.uni-koeln.de` | REST and bulk SD file |
| nmrshiftdb2 releases | `sourceforge.net` | bulk download |
| ChEMBL | `www.ebi.ac.uk` | REST |
| ChEMBL bulk | `ftp.ebi.ac.uk` | bulk release |
| RCSB PDB data | `data.rcsb.org` | REST |
| RCSB PDB search | `search.rcsb.org` | REST |
| RCSB PDB files | `files.rcsb.org` | structure download |
| BindingDB | `www.bindingdb.org` | REST and bulk download |

Deliberately excluded, and they should stay excluded: `sdbs.db.aist.go.jp` (its
disclaimer prohibits robot collection and large downloads) and
`webbook.nist.gov` (bulk use pending a documented licence for the intended
commercial product).

## Plan

In dependency order, each step reviewable on its own.

1. Data model, catalog store with explicit reversible migrations, chemical identity,
   provenance, and the source-policy manifest.
2. Provider interface plus the shared HTTP client: rate limiting, retry with
   exponential backoff and jitter, response caching, resumable jobs.
3. PubChem and nmrshiftdb2 adapters end to end, with contract tests driven by
   checked-in fixtures and optional live tests behind a flag.
4. ChEMBL, RCSB PDB and BindingDB adapters, only after step 3 passes.
5. `data/inbox` import with hashing, type and size checks, quarantine and an
   ingestion-run record. Originals are never deleted.
6. Search, dossier and ingestion-job endpoints, with measured-versus-calculated
   labelling on every value.
7. A deterministic 50 to 100 molecule pilot manifest and its coverage report.

## Single safest next action

Build step 1. It has no network dependency, it is what every later step joins
against, and getting chemical identity wrong is the one mistake that silently
corrupts everything downstream and cannot be repaired by a later re-import.
