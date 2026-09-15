# Calibration and abstention

A computed isotropic shielding is not a chemical shift. Before this module the
backend returned `chemical_shifts_ppm: null` unless the caller supplied their own
reference shieldings, which left nothing a chemist could hold against a spectrum.
This module closes that gap and attaches a coverage guarantee and an explicit
refusal to answer.

## What it does

1. Fits the method matched scaling `delta = intercept + slope * sigma` on a
   training split of a reference corpus. The literature form `delta = (a - sigma) / b`
   is reported alongside it. They are the same line.
2. Computes split conformal nonconformity scores on a disjoint calibration split.
3. Returns prediction intervals, or abstains when the split is too small.
4. Tests a measured spectrum against a candidate structure and returns a
   conformal p value.

## The guarantee

Split conformal prediction. For a molecule exchangeable with the calibration
split, the returned interval covers the truth with probability at least
`1 - alpha`. The bound is finite sample, distribution free, and independent of
whether the underlying quantum method is any good. A bad method yields wide
intervals rather than false confidence.

The exchangeable unit is the molecule, not the nucleus. Nuclei inside one
molecule share a conformer, a solvent shell and an assignment, so they are
correlated and not exchangeable with each other. The nonconformity score is
therefore the molecule level maximum absolute residual

    s = max over assigned nuclei of | observed shift - predicted shift |

and the resulting band is simultaneous over every assigned nucleus of a molecule.
A per nucleus band is also reported, marked as a diagnostic, because it assumes
nucleus level exchangeability that correlated nuclei violate.

## Why nineteen

The split conformal quantile is the k-th smallest of n calibration scores with
`k = ceil((n + 1)(1 - alpha))`. When `k > n` no such score exists and the honest
quantile is infinite. Solving `ceil((n + 1)(1 - alpha)) <= n` gives

    n >= (1 - alpha) / alpha

so 19 calibration molecules at 95 percent, 9 at 90 percent, 4 at 80 percent. At
the default half and half split that means 39, 19 and 9 molecules in the corpus.
Below those sizes `/v1/calibration/fit` returns `usable: false` with the required
count rather than a narrow interval carrying no coverage.

## Size-conditional coverage

A maximum taken over more nuclei is larger, so one pooled quantile over-covers
small molecules and under-covers large ones. Measured on 15,024 held-out real
molecules, the marginal rate was exactly nominal while the largest molecules sat
three points below it:

| Assigned carbons | Held-out molecules | Pooled quantile | Size-conditional |
|---|---|---|---|
| 0 to 4 | 1,177 | 0.961 | 0.965 |
| 5 to 9 | 5,736 | 0.957 | 0.945 |
| 10 to 14 | 5,208 | 0.947 | 0.953 |
| 15 to 19 | 2,140 | 0.944 | 0.949 |
| 20 to 24 | 629 | 0.917 | 0.952 |
| 25 to 29 | 134 | 0.918 | 0.969 |
| **all** | **15,024** | **0.9502** | **0.9505** |

The marginal rate is nominal either way. That is the point: a marginal guarantee
can be met exactly while a customer submitting a large natural product is served
at 0.917. Calibration scores are therefore binned by assigned-nucleus count and a
quantile is taken inside each bin, with bins widened until each holds enough
molecules for its own quantile. The worst bucket moves from 0.917 to 0.945 and
the marginal rate does not move. Four of the 15,024 molecules abstain, being
larger than anything in the corpus.

## Abstention

Three rules, all returned as structured `abstention` objects rather than silent
degradation.

| Reason | Trigger |
|---|---|
| `calibration_split_too_small` | The conformal quantile at the requested alpha is infinite. |
| `outside_calibration_domain` | A computed shielding falls outside the fitted calibration range, so exchangeability with the corpus is not credible. |
| `no_calibration_at_this_molecule_size` | The corpus holds no molecule with this many assigned nuclei. Borrowing the nearest bin would be a guess dressed as a bound. |

The second rule is a heuristic guard, not part of the theorem. It exists because
the guarantee is silent about molecules the corpus never covered, and silence is
not permission.

## Measured behaviour

Synthetic corpora with a molecule level offset, so nuclei are correlated the way
real ones are. 600 trials per level, 80 molecule corpora.

| alpha | Target coverage | Measured simultaneous coverage | False rejection rate | Mean half width |
|---|---|---|---|---|
| 0.05 | 0.95 | 0.952 | 0.047 | 0.416 ppm |
| 0.10 | 0.90 | 0.893 | 0.103 | 0.366 ppm |
| 0.20 | 0.80 | 0.788 | 0.202 | 0.313 ppm |

Rejection power against a decoy carrying a single displaced nucleus, alpha 0.05,
400 trials per level.

| Decoy offset | Rejected |
|---|---|
| 0.0 ppm | 3.8 percent |
| 0.3 ppm | 24.0 percent |
| 0.5 ppm | 68.0 percent |
| 0.8 ppm | 95.0 percent |
| 2.0 ppm | 96.5 percent |

Power plateaus near 96.5 rather than 100 because the domain guard abstains
instead of rejecting when a probe shielding extrapolates past the fitted range.
`tests/test_calibration.py` reruns the coverage check as an assertion.

These numbers are properties of the conformal machinery on synthetic data. They
are not accuracy claims for any real level of theory. What a real corpus changes
is the width of the interval, not whether the coverage holds.

## Measured on real data

CASCADE, 5,006 molecules and 52,986 assigned 13C nuclei, experimental shifts
against mPW1PW91/6-311+G(d,p). See `docs/HARVEST.md` for the provenance and the
selection caveat, which is serious.

| Slice | Molecules | Slope | R squared | Interval | Held-out coverage |
|---|---|---|---|---|---|
| solvent unreported | 4,623 | 0.999 | 0.9982 | 5.38 ppm | 0.950 |
| CDCl3 | 259 | 1.000 | 0.9981 | 5.69 ppm | 0.969 |

For scale, the raw method error before calibration is 2.16 ppm standard
deviation, median absolute residual 1.34 ppm, 95th percentile 4.45 ppm. The
calibrated interval is wider than the median error because it is simultaneous
over every carbon in the molecule at 95 percent, which is the number a chemist
comparing a whole spectrum actually needs.

## Computed shifts versus shieldings

Some sources publish an already-referenced computed shift rather than a raw
shielding. The two are affine images of each other, so the fit is unchanged, but
the expected slope flips sign: near minus one against a shielding, near plus one
against a shift. `computed_kind` in the provenance selects which sign check
applies, so a correct fit is not flagged as inconsistent and a genuinely wrong
one still is.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /v1/calibration/fit` | Scaling, conformal quantiles, split diagnostics, usability |
| `POST /v1/calibration/shifts` | Calibrated shifts with simultaneous intervals, or abstention |
| `POST /v1/calibration/identity` | Spectrum against candidate structure, conformal p value, or abstention |

All three are stateless: the corpus is posted with the query. Persisted and
versioned corpora are the next step and are not implemented.

## What this does not do

Calibration absorbs systematic method error. It does not correct a wrong
conformer, a wrong tautomer, a wrong protonation state or a misassignment, and
it cannot detect them. A verdict of `not_contradicted` is not confirmation of
identity, purity or novelty. It means the spectrum does not contradict the
candidate at the stated level and resolution. Only `inconsistent` is a
calibrated positive statement.

The corpus is the binding constraint. The math is complete and tested; it needs
a few hundred assigned spectra carrying solvent, temperature, reference and level
of theory metadata before the intervals mean anything about real chemistry.
