# Ingestion pilot: what the pipeline actually did

The pilot specified in the data-access plan is 50 to 100 diverse molecules across
five sources. Four of those five need network access that this environment refuses,
so that pilot could not be run. What follows is what was run instead: the complete
NMRShiftDB-derived bulk file through the real pipeline, end to end, twice.

## Run

Source: the NMRShiftDB-derived SD file distributed with CASCADE, 7,997 structures.

```
9,266 spectrum records processed in 26 s (363 records/second)
```

| Outcome | Run 1 | Run 2 |
|---|---|---|
| fetched | 6,261 | 6,261 |
| inserted | 18,325 | **0** |
| updated | 0 | **0** |
| unchanged | 458 | 18,783 |
| rejected | 3,005 | 3,005 |

Run 2 changing nothing is the point. Ingestion is interrupted constantly in practice,
so a second run must verify the catalog rather than rewrite it. Getting to that took
fixing three separate leaks, described in the commit history.

## What landed

| Table | Rows |
|---|---|
| molecule | 6,032 |
| spectrum | 6,261 |
| spectrum_peak | 71,661 |
| experimental_conditions | 167 |
| source_record | 9,266 |
| molecule_xref | 6,032 |
| validation_issue | 17,485 |

Catalog size 30.6 MB, about 5.1 kB per molecule including full provenance and every
rejection reason.

| Scale | Projected catalog |
|---|---|
| 1,000 molecules | 5 MB |
| 100,000 molecules | 508 MB |
| 1,000,000 molecules | 5.1 GB |

Storage is not the constraint. Adding other modalities, raw payload blobs and protein
structures will move these numbers, but a million-molecule spectral catalog is an
ordinary disk, not a data-centre problem.

## Data quality findings

**Measured and calculated are now separated.** 57 spectra across 43 molecules are
computed predictions, not measurements. NMRShiftDB does not flag them in any
"Spectrum Type" field; it flags them by carrying a level of theory or a prediction
program for that spectrum number. The earlier harvest filter looked at the wrong field
and would have let all 57 into an experimental calibration set.

**3,005 records rejected, all for one reason.** They are 1H spectra on structures
stored without explicit hydrogens, so the assignment indices address the heavy atom
carrying the proton rather than the proton itself. Mapping them would require
inferring which hydrogen is meant, which is a guess. They are stored as rejected with
the reason attached, not discarded silently.

**Provenance, not volume, is the binding constraint.** Of 6,032 molecules ingested,
**601** have a recorded solvent. None has a recorded reference compound. So the
catalog contains six thousand molecules and a few hundred that can support a
solvent-specific claim. Harvesting more of this source does not fix that; the metadata
was never entered upstream.

| Validation issue | Count |
|---|---|
| reference compound unrecorded | most measured spectra |
| solvent unrecorded | majority |
| undefined stereochemistry | substantial |
| unusable source record | 3,005 |

## What is still blocked

| Provider | Status |
|---|---|
| nmrshiftdb2 bulk | working, shown above |
| PubChem | adapter complete, tested on fixtures, never reached live |
| ChEMBL, RCSB PDB, BindingDB | not implemented |

The five-source, 50 to 100 molecule pilot with cross-source agreement checking is the
real acceptance test, and it needs the allowlist in `PHASE_0_REPORT.md` approved
before it can run. No code change should be required at that point.
