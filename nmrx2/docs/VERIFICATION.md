# Verification record

Final command: `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest -q`

**19 passed, 2 dependency deprecation warnings, 4.35 seconds** in this environment. Exact dependency versions are in `tested-versions.json`; the full final test output is in `examples/test-results.txt`.

| Check | Evidence | Limit |
|---|---|---|
| Authentication and tenant isolation | Missing key rejected; other owner gets 404 | Not a penetration test |
| Molecule validation | Invalid strings, salts, metals and radicals rejected; unspecified stereo warning | Narrow domain, no exhaustive stereochemical audit |
| Persistent queue | Atomic claim, terminal update, actual child-process quantum execution | Single host; no crash lease recovery |
| Numerical utilities | Boltzmann normalization, robust fit ordering, analytic diatomic mode count | No uncertainty calibration |
| Water HF orbitals | Real energy near -75 Hartree at HF/STO-3G; occupied/virtual checks | Broad regression bounds, not spectroscopy accuracy |
| Water harmonic IR | Three real modes; numerical frequencies agree within 2 cm^-1 with independent analytic PySCF Hessian at same geometry | Same engine/method; not experimental validation |
| Water NMR | HF and B3LYP shieldings; equivalent H agreement within 0.05 ppm | No external reference benchmark or general error estimate |
| Docking | Real Vina execution, finite score, pose output on synthetic one-atom fixture | Not a protein benchmark or biological validation |
| AI integration | Mocked HTTP provider checks request privacy fields and text extraction | No live provider call or factual quality evaluation |

Real water example output files contain HF/STO-3G results. Water IR frequencies are approximately 2169.94, 4139.34 and 4390.28 cm^-1. These unscaled minimal-basis harmonic values are **not experimental water frequencies**. NMR example values are shieldings, not referenced chemical shifts.

Issues found and corrected during testing: SQL placeholder count, old properties-extension response batch assumptions, DFT grid block alignment and callable preservation, and container /proc memory-reporting availability. A conservative peak-RSS fallback handles absent Linux process memory telemetry. These fixes leave physical coupled response enabled.

Untested: Docker build/compose startup, public deployment, heavy load, worker crash recovery, real protein redocking/enrichment, broad molecular datasets, absolute IR intensities, solvent/conformer predictions, and live external AI. This is a tested research alpha, not scientific or operational production certification.
