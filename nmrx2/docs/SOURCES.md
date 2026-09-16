# Which sources can actually feed the calibration layer

Ranked by the only three things that decide it. Run
`python -c "from nmrx.harvest.sources import calibration_report; print(calibration_report())"`
for the live version.

| Source | Score | Measured | Assignments | Conditions | Bulk | Commercial | Usable now |
|---|---|---|---|---|---|---|---|
| BMRB (metabolomics) | 6/6 | yes | yes | yes | yes | allowed | **yes** |
| GISSMO | 6/6 | yes | yes | yes | yes | allowed | **yes** |
| CHESHIRE | 6/6 | yes | yes | yes | no | restricted | no |
| SDBS | 6/6 | yes | yes | yes | no | prohibited | no |
| CASCADE | 5/6 | yes | yes | partial | yes | share-alike | **yes** |
| Chemotion | 5/6 | yes | partial | yes | yes | allowed | **yes** |
| NMRShiftDB2 | 5/6 | yes | yes | partial | yes | share-alike | **yes** |
| nmrXiv | 5/6 | yes | partial | yes | yes | allowed | **yes** |
| HMDB | 4/6 | mixed | partial | yes | yes | restricted | yes |
| NIST WebBook | 4/6 | yes | no | yes | no | prohibited | no |
| RIKEN SpectralDB | 4/6 | yes | partial | partial | no | restricted | no |

## Why these three criteria and nothing else

A source can be enormous and still be useless here if it misses any one of them.

**Measured.** Calibrating a prediction against another prediction measures nothing.
Several sources mix predicted spectra in with measured ones without flagging them
clearly, so this has to be checked per record, not per source.

**Assignments.** Each shift must be tied to a specific atom. A peak list saying "there
are signals at 128.5 and 21.0 ppm" cannot be paired with a calculation, because
nothing says which carbon is which.

**Conditions.** Solvent and reference compound. Shifts are not comparable across
solvents, and an unrecorded reference is an unknown offset applied to every value in
the record. This is the one most sources neglect, and it is the one currently limiting
this project: of 6,032 molecules ingested from NMRShiftDB, 601 record a solvent and
none records a reference compound.

Conditions can sometimes be recovered by filtering to the subset that has them. A
missing assignment or an unlabelled prediction cannot be recovered at all.

## What each source adds

**Worth connecting next, in order**

1. **BMRB metabolomics.** Scores 6/6, openly licensed with no share-alike, and its
   conditions metadata is the best of any open source. Smaller than NMRShiftDB but
   every record is more useful per molecule. This is the best next connector.
2. **GISSMO.** Also 6/6 and openly licensed, with unusually complete field, solvent and
   pH. It is 1H only, and 1H is harder to calibrate than 13C because the shift range is
   narrow and solvent effects are proportionally larger. Good second target.
3. **Chemotion.** Fed from electronic lab notebooks, so conditions are recorded as a
   matter of course rather than as an afterthought. Assignment depends on the
   depositor, so it needs a survey before committing to a connector.
4. **nmrXiv.** Modern deposits carry full acquisition metadata; per-atom assignment
   depends on whether the depositor supplied NMReDATA.

**Already connected**

- **NMRShiftDB2** (bulk file) and **CASCADE**. CASCADE remains the only public source
  carrying both measured shifts and DFT values at a fixed level.

**Not worth new engineering**

- **NIST WebBook.** Gas-phase IR is scientifically the best match for a gas-phase
  harmonic calculation, which makes its access terms genuinely costly. It has no
  per-atom assignments, so it cannot feed NMR calibration at all. Licence it for IR if
  IR becomes a product, do not scrape it.
- **SDBS.** Scientifically ideal, 6/6 on every criterion, and closed. Bulk collection
  is prohibited by its disclaimer. Disabled in `nmrx/data/policy.py`, and enabling it
  needs a written agreement, not a code change.
- **Zenodo and similar repositories.** Real data, no common schema. A curated manual
  route through the inbox, not a connector.

## The format that removes the connector problem

**NMReDATA** is an SDF extension that carries the structure, the per-atom assignment
and the experimental conditions in a single file. It is the only common format that
does. `nmrx/data/inbox.py` reads it, which means data obtained by any route at all,
a collaborator's supplementary file, a licensed purchase, or your own spectrometer,
enters the catalog with full provenance and no new connector.

For a project whose binding constraint is recorded conditions rather than volume, a
few hundred NMReDATA records are worth more than tens of thousands of bare peak lists.
