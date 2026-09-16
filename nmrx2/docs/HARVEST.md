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
open source with per-atom assignments, and it carries a share-alike licence.

Be precise about what that does and does not mean, because it is widely
overstated. Share-alike here is a database licence, not software copyleft. It
does not require NMRx to be free or open source, it does not reach your
application code, your calculations, your models or your interface, and it does
not prevent you charging for a service. What it governs is redistribution of the
database: if you publish the source database, or a derived database built from
it, that published copy may have to carry the same licence and attribution.

So the question to get reviewed is narrow and answerable: does your calibration
corpus count as a derived database, and are you redistributing it or only using
it internally to serve predictions. Those two cases have different answers. Ask
a lawyer that specific question rather than a general one about whether you can
sell the product.

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

## What was actually harvested

Only code hosts were reachable from the build environment, so every scientific
database returned 403 and the harvest ran against public git repositories.

**CASCADE** (Paton lab, Chem. Sci. 2021) turned out to be the most valuable
public source found, because it is the only one carrying both halves of a
calibration record: experimental 13C shifts and DFT values at one fixed level.
5,006 molecules and 52,986 assigned carbons survive the pipeline.

Two findings about it, both load-bearing.

**Do not join NMR8K to DFT8K by atom index.** The 2D and 3D files do not share
atom numbering. Joining them directly gives residuals with a 99th percentile of
93 ppm and a maximum of 208 ppm, which is misalignment, not method error. The
conformal layer reported it honestly as 87 to 141 ppm intervals, which is what a
calibration layer is for. Shifts are therefore taken from Exp5K, CASCADE's own
curated pairing, and NMRShiftDB metadata is joined per molecule only.

**Exp5K is filtered by agreement.** It is the subset of NMR8K that already
matched the DFT calculation, about five thousand of eight thousand molecules,
with residuals truncated near 6 ppm. The molecules where the method fails were
removed before calibration, so intervals fitted on it are optimistic for
molecules from the wild. Every corpus this adapter builds carries that warning.
It should not be edited out, and coverage should be re-validated on a corpus that
was never filtered by agreement before it is quoted to a user.

### Provenance is the binding constraint, not volume

Parsing the raw NMRShiftDB-derived SDF gives 9,266 spectrum records over 7,997
molecules. After removing 1H assignments that cannot be indexed because the
structures carry implicit hydrogens, 6,261 remain. Of those:

| Field | Recorded |
|---|---|
| Solvent | 630 of 6,261 |
| Reference compound | 0 of 6,261 |
| Field strength | 520 of 6,261 |

So the largest properly-provenanced slice is 13C in CDCl3 with an unrecorded
reference, a few hundred molecules, not tens of thousands. The rest is one large
pool whose solvent nobody wrote down. That pool still calibrates, and the code
labels it `mixed_or_unreported` rather than pretending otherwise, but it cannot
support a claim about any particular solvent.

## The expensive half

Every surviving molecule still needs a GIAO NMR calculation at the corpus level
of theory, because no database carries computed shieldings. `cli.py jobs` emits
those payloads. This is the real cost of the project and it does not shrink with
better scraping.

Two practical consequences:

- Harvest broadly, compute selectively. Choose the slice you intend to serve
  first, usually 13C in CDCl3 referenced to TMS, and compute only that.
- Benchmark one representative molecule at your chosen level before committing to
  a corpus size. Measured single-threaded with no geometry optimisation:

| Molecule | Atoms | STO-3G | def2-SVP |
|---|---|---|---|
| ethanol | 9 | 4.8 s | 14.7 s |
| phenol | 13 | 16.2 s | 71.2 s |
| paracetamol | 20 | 46.2 s | 378 s |
| ibuprofen | 33 | 123 s | 1,262 s |

  A drug-sized molecule at def2-SVP is 21 CPU-minutes before any geometry
  optimisation, and def2-TZVP is substantially worse. A thousand-molecule corpus
  at that size is on the order of 350 CPU-hours. This is why CASCADE matters: its
  DFT half is already computed.

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
