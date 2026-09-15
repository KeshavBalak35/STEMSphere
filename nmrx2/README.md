# NMRx 2.0 — research backend

Runnable Python/FastAPI research alpha: PySCF electronic structure, GIAO NMR shielding, finite-difference harmonic IR, RDKit molecular preparation, AutoDock Vina docking, persistent job queue, and optional AI explanations.

This is a standalone backend, not a deployed consumer site or a production-ready universal chemistry platform. No prior NMRx code was supplied. Interactive API documentation is at `/docs` after startup.

## Start

Use Python 3.11 or 3.12 on Linux in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[quantum,docking,test]'
python -m pip install pyscf-properties==0.1.0
export NMRX_API_KEYS='{"demo":"replace-this-with-at-least-24-random-characters"}'
export NMRX_DB="$PWD/data/jobs.sqlite3"
python -m uvicorn nmrx.api:app --host 127.0.0.1 --port 8000
```

In another terminal, activate the same environment, set the same absolute `NMRX_DB`, then run `python -m nmrx.worker`.

Alternatively copy `.env.example` to `.env`, replace the key, and run `docker compose up --build`. The Docker image includes scientific extras. Docker startup itself was not tested here.

```bash
curl http://127.0.0.1:8000/v1/jobs/quantum \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: replace-this-with-at-least-24-random-characters' \
  -d '{"smiles":"O","task":"orbitals","method":"HF","basis":"sto-3g"}'
```

Poll `/v1/jobs/<returned-id>` with the same key. Status progresses through queued, running, succeeded/failed. Results include units, convergence, warnings, dependency versions and input hash. Requests are retained in SQLite and may contain confidential chemistry.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Process health |
| `POST /v1/molecules/validate` | Valence, descriptors, conformer preparation |
| `POST /v1/jobs/quantum` | Orbitals, IR or NMR |
| `POST /v1/jobs/docking` | Prepared-receptor docking |
| `GET /v1/jobs/{id}` | Owner-scoped job and results |
| `POST /v1/validation/spectral-fit` | Explicitly assigned peak comparison |
| `POST /v1/calibration/fit` | Scaling and conformal quantiles from a reference corpus |
| `POST /v1/calibration/shifts` | Calibrated shifts with simultaneous coverage intervals |
| `POST /v1/calibration/identity` | Spectrum against candidate structure, or abstention |
| `POST /v1/guide` | Local checklist or opt-in external AI |

## Scope

- Single connected closed-shell molecules containing H,C,N,O,F,Si,P,S,Cl,Br with MMFF parameters. Maximum 80 atoms including H; queued IR maximum 30. Unsynthesized molecules are accepted under the same constraints. Successful calculation does not establish synthesizability or identity.
- Gas-phase RHF/B3LYP/PBE0 with STO-3G/def2-SVP/def2-TZVP. STO-3G is for inexpensive software checks, not final accuracy claims.
- Lowest sampled converged MMFF conformer, optional geomeTRIC optimization. No verified global minimum, protonation/tautomer enumeration or automatic thermodynamic ensemble. `mathcore.ensemble` is a separate Python utility.
- NMR returns atom-indexed shieldings. Shifts remain null unless caller supplies reference shieldings and method/environment provenance. No invented reference values or spin-coupling/multiplet simulation.
- Calibration converts shieldings to shifts with a distribution-free coverage guarantee, and abstains when the corpus cannot support the requested level. See `docs/CALIBRATION.md`. The math is tested; no reference corpus ships with this release.
- `nmrx.harvest` ingests public spectral databases into calibration corpora, carrying licence status per source and refusing sources whose terms prohibit bulk retrieval. See `docs/HARVEST.md`. No data is bundled.
- IR returns unscaled harmonic frequencies and normalized relative intensities, not absolute km/mol. Imaginary modes are flagged.
- Docking requires externally prepared rigid receptor PDBQT, a justified box and preparation notes. Meeko prepares the ligand; Vina returns scores and poses. No automatic receptor repair, pocket detection, covalent or metal-aware docking.
- No radicals, metals, salts/mixtures, excited states, periodic systems or whole-protein QM in this release. No orbital cube export.

## AI

Configure `OPENAI_API_KEY` and `NMRX_AI_MODEL` to a model your account supports. No default model is silently chosen. `/v1/guide` defaults to a local deterministic checklist. Set `use_external_ai: true` for question-specific explanations. The question and selected computed results/warnings are sent externally; structure and pose files are excluded from job context, but anything in the question is sent. `store: false` is used; it is not a zero-retention promise.

The AI cannot execute code or jobs. It explains evidence and can still be wrong. Live external AI was not exercised without credentials; its request/response integration is tested with a mocked provider.

## Operations

Included: API-key owner isolation, bounded request bytes, finite numeric validation, queue quotas, atomic claiming, process-separated workers, job timeouts, compute-only child environment, provenance and non-root Docker execution.

Before public release: add OIDC/SSO, TLS, per-user rate/spend limits, leased durable queue/PostgreSQL, isolated compute containers and network policy, protected object storage, monitoring, retention/deletion, backup/migration testing, license inventory, dependency audit, and scientific benchmark gates. No frontend, billing, automatic cancellation, or distributed scheduler is included.

A worker crash can leave a running job. Stop/reconcile its child process before an operator marks it failed; this alpha does not automatically requeue or implement leases. SQLite is for a single-host pilot. `tested-versions.json` records this environment; dependencies must be resolved and hash-locked for deployment.

Run `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest -q`. Read `docs/VERIFICATION.md` for actual evidence, `docs/SCIENCE.md` for equations, and `docs/PRODUCT.md` for competitive positioning.

## Harvest

`python -m nmrx.harvest.cli sources` lists every public spectral source with its
licence, bulk-access status and whether it is usable commercially. `ingest` parses
a bulk file into filtered, deduplicated records and reports which provenance
slices are large enough to calibrate. `jobs` emits the quantum NMR payloads the
corpus still needs, because no public database carries computed shieldings.

Sources whose terms prohibit bulk download are excluded by policy, not by
capability. See `docs/HARVEST.md`.

`nmrx.harvest.cascade` downloads and pairs the CASCADE dataset, the one public
source found that ships both experimental 13C shifts and DFT values at a fixed
level. About 5,000 molecules and 53,000 assigned carbons. Its selection caveat is
attached to every corpus it builds and matters: the set is filtered by agreement
with the calculation, so intervals fitted on it are optimistic.
