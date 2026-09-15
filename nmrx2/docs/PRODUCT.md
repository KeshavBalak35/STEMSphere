# Product opportunities

The [official Q-Chem feature overview](https://www.q-chem.com/explore/) already describes extensive spectroscopy, NMR improvements, solvation, cloud access and Python interfacing, as well as biomolecular/QM-MM capabilities. “Q-Chem cannot do NMR, cloud, Python or proteins” is therefore not a defensible sales claim. This is a focused review, not an exhaustive competitor audit.

| Opportunity to validate with customers | Delivered here | Next implementation | Evidence needed |
|---|---|---|---|
| Guided molecule-to-spectra-to-docking workflow | Shared API and guide | Unified frontend, atom-linked spectra and poses | Task completion time vs current workflows |
| Clear uncertainty and limitations | Convergence, references, warnings, residual score | Held-out calibration and abstention | Error and coverage by chemical family |
| Reproducible handoff | Inputs, hash, dependency versions, units | Immutable downloadable run bundles | Independent reproduction |
| Cost visibility | Queue bounds and timeout | Empirical compute estimates and budget routing | Cost and prediction-time accuracy |
| Experimental structure comparison | Assigned-peak residuals | Spectrum import, missing-peak penalties, candidate ranking | Blinded candidate sets |
| Accessible protein workflow | PDBQT receptor, Meeko ligand and Vina poses | Receptor review and pose-quality gates | Redocking, clashes, enrichment |
| Private chemistry projects | Local compute; opt-in AI | Encrypted self-hosted projects and audit controls | Customer requirements and security testing |

These are inferred opportunities, not proven exclusive gaps. Integration quality, interpretation and reliable validation are stronger initial differentiators than claiming a new quantum solver.

Suggested sequence: private pilot on simple organic molecules; measure accuracy, failures and time saved; add spectrum ingestion and uncertainty calibration; extend receptor preparation; then expand supported chemistry and public infrastructure. Interview synthesis groups, small medicinal-chemistry teams and teaching labs. No pricing, revenue or superiority claim follows from this build alone.

The AI uses the optional [OpenAI Responses API](https://developers.openai.com/api/docs/quickstart); numerical results come from chemistry engines.
