# Harvesting public spectral data

The goal is a calibration corpus: molecules carrying both a measured chemical
shift and a computed shielding at one fixed level of theory. Public databases
supply the first half. Nothing public supplies the second.

## What is actually open

Run `python -m nmrx.harvest.cli sources` for the live registry. The summary that
matters for a commercial product:

| Source | Spectra | Bulk download | Commercial use |
|---|---|---|---|
| NMRShiftDB2, about 44,000 assigned 1H and 13C | yes | yes | **share-alike** |
| nmrXiv | yes | yes | per dataset, commonly permissive |
| BMRB metabolomics | yes | yes | free |
| HMDB, about 1,500 experimental | yes | yes | academic only, paid licence to sell |
| NIST WebBook gas-phase IR | yes | **no** | terms restrict systematic retrieval |
| SDBS, about 34,000 IR and NMR | yes | **no** | bulk download and redistribution prohibited |
| Wiley, Bio-Rad, ACD | yes | no | proprietary |

Two consequences worth deciding early rather than late.

**The largest open collection is share-alike.** NMRShiftDB2 is the only large
open source with per-atom assignments, and it carries a share-alike licence. A
corpus derived from it may inherit that licence. If the calibrated corpus is
meant to be the defensible asset, get an opinion before it becomes the
foundation rather than after.

**The largest matching collections are closed.** SDBS and the NIST IR set are
exactly what a broad harvest would want and both restrict bulk retrieval. This
pipeline excludes them by policy. Scraping them would put a product with paying
users in direct breach, and the exposure scales with revenue. For a few hundred
well-documented spectra, licensing is likely cheaper than the engineering needed
to assemble the same thing from scattered open sources.

## Why the harvest shrinks

Conformal coverage holds within one exchangeable population. A corpus mixing
solvents, reference compounds or nuclei is not one population, so a harvest must
be sliced along its provenance before it is counted:

    (nucleus, solvent, reference compound, field)

Each slice is its own corpus with its own scaling and its own quantile, and each
needs 39 molecules independently at alpha 0.05 with a half and half split. Slices
below that threshold cannot be pooled to reach it. Pooling is precisely the thing
the guarantee forbids.

`cli.py ingest` reports this directly: how many slices exist, how many clear the
threshold, and how many molecules are stranded below it. Expect the stranded
count to be large. A 44,000 record harvest is not a 44,000 molecule corpus.

## The expensive half

Every surviving molecule still needs a GIAO NMR calculation at the corpus level
of theory, because no database carries computed shieldings. `cli.py jobs` emits
those payloads. This is the real cost of the project and it does not shrink with
better scraping.

Two practical consequences:

- Harvest broadly, compute selectively. Choose the slice you intend to serve
  first, usually 13C in CDCl3 referenced to TMS, and compute only that.
- Benchmark one representative molecule at your chosen level before committing to
  a corpus size. Cost scales steeply with basis set and atom count, so measure it
  rather than estimating it.

## Pipeline

```bash
python -m nmrx.harvest.cli sources
python -m nmrx.harvest.cli ingest nmrshiftdb2.sdf --nucleus 13C --min-nuclei 3 --out records.json
python -m nmrx.harvest.cli jobs records.json --basis def2-tzvp --out jobs.json
# submit jobs.json to /v1/jobs/quantum, collect isotropic_shielding_ppm
# then normalize.to_calibration_set(records, shieldings, provenance)
# then POST the result to /v1/calibration/fit
```

## Refusals built into the pipeline

These are deliberate and will look like the pipeline discarding useful data. It
is discarding data that would quietly invalidate the guarantee.

| Refusal | Reason |
|---|---|
| Unknown solvent normalises to `None`, not a guess | Solvent is part of the provenance key. A wrong guess merges non-exchangeable populations. |
| `reference_compound` is never defaulted to TMS | An assumed reference is an unmeasured systematic offset. |
| Predicted spectra dropped by default | Calibrating a prediction against a prediction measures nothing. |
| Ambiguous atom index base marked unusable | A half-right assignment is worse than none. |
| 1H assignments without explicit hydrogens marked unusable | The index addresses the heavy atom, not the proton. |
| Shifts outside the plausible nucleus window dropped | One transcription error widens every interval in the corpus. |
| Duplicate molecules collapsed | A repeated molecule narrows intervals without justification. |
| `to_calibration_set` raises rather than dropping a missing shielding | Silent dropping changes what was calibrated. |
