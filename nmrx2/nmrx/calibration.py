"""Distribution-free calibration and abstention for computed NMR shieldings.

The quantum module returns isotropic shieldings. A shielding is not a chemical
shift and is not comparable to a measured spectrum until a reference and a
method-matched scaling are supplied. This module performs that conversion and,
more importantly, attaches a finite-sample prediction interval and an explicit
abstention rule.

Guarantee. Split conformal prediction. The scaling regression is fitted on a
proper training split; nonconformity scores are computed on a disjoint
calibration split. For a new molecule exchangeable with the calibration split,
the returned interval covers the truth with probability at least 1 - alpha.
The bound is finite-sample and holds for any underlying prediction function.
It is not a statement about molecules drawn from a different chemical space,
a different level of theory, or a different solvent.

Exchangeable unit. Nuclei inside one molecule are correlated, so nuclei are not
exchangeable with each other. Molecules are. The molecule-level maximum score is
therefore the defensible object and is what the identity verdict uses. The
per-nucleus band is reported as a diagnostic and is labelled as assuming
nucleus-level exchangeability, which correlated nuclei violate.

Abstention. When the calibration split is smaller than the size the conformal
quantile requires, the honest interval is infinite. This module returns an
explicit abstention carrying the required size rather than a narrow interval
with no coverage.
"""
import hashlib
import math

import numpy as np

# Provenance fields that must match across every record in a calibration set.
# Mixing levels of theory or solvents silently destroys the exchangeability the
# coverage guarantee rests on, so this is enforced rather than warned about.
PROVENANCE_KEYS = ("method", "basis", "nucleus", "solvent", "reference_compound")

# Some sources publish an already-referenced computed shift rather than a raw
# shielding. The two are affine images of each other, so the scaling fit is
# unchanged, but the expected slope sign flips and a sign check that ignores
# this would flag every correct fit.
COMPUTED_KINDS = ("shielding", "shift")


def minimum_calibration_size(alpha):
    """Smallest calibration split size with a finite conformal quantile.

    The split conformal quantile is the k-th smallest of n scores with
    k = ceil((n + 1)(1 - alpha)). When k > n no such score exists and the
    honest quantile is infinite. Solving ceil((n + 1)(1 - alpha)) <= n gives
    n >= (1 - alpha) / alpha, so alpha = 0.05 requires 19 molecules and
    alpha = 0.1 requires 9.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie strictly between 0 and 1")
    return int(math.ceil((1 - alpha) / alpha))


def conformal_quantile(scores, alpha):
    """Return the split conformal quantile and whether it is finite."""
    s = np.sort(np.asarray(scores, dtype=float))
    n = s.size
    if n == 0 or not np.isfinite(s).all():
        raise ValueError("Finite nonconformity scores required")
    k = int(math.ceil((n + 1) * (1 - alpha)))
    if k > n:
        return math.inf, k, False
    return float(s[k - 1]), k, True


def conformal_pvalue(scores, new_score):
    """Valid conformal p-value for a new score under exchangeability.

    p = (1 + #{calibration scores >= new score}) / (n + 1). Under exchangeability
    this is stochastically larger than uniform, so rejecting when p <= alpha has
    type I error at most alpha.
    """
    s = np.asarray(scores, dtype=float)
    return float((1 + int(np.sum(s >= new_score))) / (s.size + 1))


def size_groups(counts, alpha):
    """Adjacent bins over assigned-nucleus count, each large enough for the quantile.

    A molecule-level maximum grows with the number of nuclei it is taken over, so
    one pooled quantile over-covers small molecules and under-covers large ones.
    Measured on real 13C data the marginal rate was exactly nominal while the
    largest molecules sat several points below it. Splitting the calibration
    scores by size and taking a quantile inside each bin restores coverage
    conditional on size, at the cost of needing enough molecules in every bin.
    """
    need = minimum_calibration_size(alpha)
    ordered = sorted(counts)
    if len(ordered) < need:
        return []
    edges, start = [], 0
    while start < len(ordered):
        stop = start + need
        if len(ordered) - stop < need:      # absorb a short tail into the last bin
            stop = len(ordered)
        low = ordered[start]
        high = ordered[stop - 1] if stop < len(ordered) else ordered[-1]
        while stop < len(ordered) and ordered[stop] == high:
            stop += 1                        # never split one size across two bins
            high = ordered[stop - 1] if stop <= len(ordered) else high
        if edges and low <= edges[-1][1]:
            low = edges[-1][1] + 1
        if low > high:
            edges[-1] = (edges[-1][0], high)
        else:
            edges.append((low, high))
        start = stop
    merged = []
    for low, high in edges:
        if merged and sum(1 for c in ordered if merged[-1][0] <= c <= merged[-1][1]) < need:
            merged[-1] = (merged[-1][0], high)
        else:
            merged.append((low, high))
    if len(merged) > 1 and sum(1 for c in ordered if merged[-1][0] <= c <= merged[-1][1]) < need:
        merged[-2] = (merged[-2][0], merged[-1][1]); merged.pop()
    return merged


def _provenance_key(provenance):
    missing = [k for k in PROVENANCE_KEYS if not provenance.get(k)]
    if missing:
        raise ValueError("Calibration provenance requires " + ", ".join(missing))
    return {k: str(provenance[k]) for k in PROVENANCE_KEYS}


def _fingerprint(key, records):
    blob = repr(key) + "|" + "|".join(sorted(r["id"] for r in records))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _pairs(record):
    """Flatten one record to matched (shielding, observed shift) arrays."""
    nuclei = record["nuclei"]
    if not nuclei:
        raise ValueError("Record " + record["id"] + " has no assigned nuclei")
    x = np.array([float(n["shielding_ppm"]) for n in nuclei])
    y = np.array([float(n["observed_shift_ppm"]) for n in nuclei])
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("Record " + record["id"] + " contains nonfinite values")
    return x, y


def _split(records, train_fraction, seed):
    """Deterministic molecule-level split.

    The split is keyed on a hash of the record id and the seed, so the same set
    always produces the same split regardless of submission order. Splitting on
    molecules rather than nuclei is what keeps the calibration scores
    exchangeable.
    """
    ordered = sorted(records, key=lambda r: hashlib.sha256((str(seed) + r["id"]).encode()).hexdigest())
    cut = int(round(len(ordered) * train_fraction))
    cut = min(max(cut, 1), len(ordered) - 1)
    return ordered[:cut], ordered[cut:]


def fit_scaling(shieldings, shifts, computed_kind="shielding"):
    """Ordinary least squares of observed shift on the computed predictor.

    Reported in both the affine form delta = intercept + slope * x and the
    literature form delta = (a - x) / b, which are the same line. With a raw
    shielding the slope must be negative, because shielding falls as shift rises.
    With an already-referenced computed shift it must be positive and near one.
    """
    if computed_kind not in COMPUTED_KINDS:
        raise ValueError("computed_kind must be one of " + repr(COMPUTED_KINDS))
    x = np.asarray(shieldings, dtype=float)
    y = np.asarray(shifts, dtype=float)
    if x.size < 2 or x.shape != y.shape:
        raise ValueError("At least two matched points required")
    if np.ptp(x) == 0:
        raise ValueError("Computed shieldings are constant; no scaling is identifiable")
    slope, intercept = np.polyfit(x, y, 1)
    residual = y - (intercept + slope * x)
    total = float(np.sum((y - y.mean()) ** 2))
    fit = {
        "slope": float(slope),
        "intercept": float(intercept),
        "literature_form": {"a": float(-intercept / slope), "b": float(-1.0 / slope)},
        "r_squared": float(1 - np.sum(residual**2) / total) if total > 0 else None,
        "training_rmse_ppm": float(np.sqrt(np.mean(residual**2))),
        "training_nuclei": int(x.size),
        "shielding_range_ppm": [float(x.min()), float(x.max())],
    }
    fit["computed_kind"] = computed_kind
    if computed_kind == "shielding" and slope >= 0:
        fit["warning"] = ("Positive slope against a shielding: shielding should fall as shift rises. "
                          "Check sign conventions, reference, or set consistency.")
    if computed_kind == "shift" and slope <= 0:
        fit["warning"] = ("Negative slope against a computed shift: a referenced prediction should track "
                          "the measurement. Check whether the column is actually a shielding.")
    return fit


def build(calibration_set, alpha=0.05, train_fraction=0.5, seed=42, computed_kind="shielding"):
    """Fit the scaling and conformal quantiles for one calibration set.

    Returns a model dictionary, or an abstention when the calibration split
    cannot support the requested alpha.
    """
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must lie strictly between 0 and 1")
    key = _provenance_key(calibration_set.get("provenance", {}))
    records = calibration_set.get("records", [])
    ids = [r["id"] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Calibration record ids must be unique")
    needed = minimum_calibration_size(alpha)
    minimum_total = int(math.ceil(needed / (1 - train_fraction))) + 1
    if len(records) < 2:
        raise ValueError("A calibration set needs at least two molecules")

    train, calib = _split(records, train_fraction, seed)
    tx = np.concatenate([_pairs(r)[0] for r in train])
    ty = np.concatenate([_pairs(r)[1] for r in train])
    fit = fit_scaling(tx, ty, computed_kind=computed_kind)

    def predicted(record):
        x, y = _pairs(record)
        return y - (fit["intercept"] + fit["slope"] * x)

    residuals = [np.abs(predicted(r)) for r in calib]
    molecule_scores = np.array([float(r.max()) for r in residuals])
    nucleus_scores = np.concatenate(residuals)

    molecule_q, molecule_k, molecule_ok = conformal_quantile(molecule_scores, alpha)
    nucleus_q, _, nucleus_ok = conformal_quantile(nucleus_scores, alpha)

    sizes = np.array([len(r) for r in residuals])
    groups = []
    for low, high in size_groups(sizes.tolist(), alpha):
        inside = molecule_scores[(sizes >= low) & (sizes <= high)]
        q, k, ok = conformal_quantile(inside, alpha) if inside.size else (math.inf, 0, False)
        groups.append({"min_nuclei": int(low), "max_nuclei": int(high),
                       "calibration_molecules": int(inside.size),
                       "interval_ppm": q if ok else None, "usable": bool(ok)})

    model = {
        "fingerprint": _fingerprint(key, records),
        "provenance": key,
        "alpha": alpha,
        "target_coverage": 1 - alpha,
        "computed_kind": computed_kind,
        "scaling": fit,
        "split": {
            "train_molecules": len(train),
            "calibration_molecules": len(calib),
            "calibration_nuclei": int(nucleus_scores.size),
            "train_fraction": train_fraction,
            "seed": seed,
        },
        "molecule_interval_ppm": molecule_q if molecule_ok else None,
        "size_conditional_groups": groups,
        "size_conditional": bool(groups),
        "molecule_quantile_rank": molecule_k,
        "nucleus_interval_ppm": nucleus_q if nucleus_ok else None,
        "calibration_scores_ppm": molecule_scores.tolist(),
        "calibration_score_sizes": sizes.tolist(),
        "usable": molecule_ok,
        "warnings": [
            "Coverage holds only for molecules exchangeable with the calibration split: same level of theory, solvent, reference and comparable chemical space.",
            "The molecule interval is simultaneous over every assigned nucleus in a molecule. The nucleus interval assumes nucleus-level exchangeability, which correlated nuclei inside one molecule violate, and is a diagnostic only.",
            "Calibration absorbs systematic method error. It does not correct a wrong conformer, a wrong tautomer or a misassignment.",
        ],
    }
    if not molecule_ok:
        model["abstention"] = {
            "reason": "calibration_split_too_small",
            "calibration_molecules": len(calib),
            "required_calibration_molecules": needed,
            "required_total_molecules_at_this_split": minimum_total,
            "detail": "The conformal quantile at alpha=" + repr(alpha) + " needs the " + str(molecule_k)
            + "th smallest of " + str(len(calib)) + " scores, which does not exist. The honest interval is infinite.",
        }
    return model


def _interval_for(model, count):
    """Size-conditional half width when the model has groups, else the pooled one.

    A molecule larger than every calibration molecule gets no interval: the corpus
    contains no evidence about that size and widening the nearest bin would be a
    guess dressed as a bound.
    """
    groups = model.get("size_conditional_groups") or []
    if not groups:
        return model["molecule_interval_ppm"], None
    for g in groups:
        if g["min_nuclei"] <= count <= g["max_nuclei"]:
            return (g["interval_ppm"], g) if g["usable"] else (None, g)
    return None, None


def _domain_flags(model, shieldings):
    low, high = model["scaling"]["shielding_range_ppm"]  # range of the computed predictor
    x = np.asarray(shieldings, dtype=float)
    outside = [int(i) for i in np.flatnonzero((x < low) | (x > high))]
    return outside


def predict(model, shieldings, atom_symbols=None):
    """Convert computed shieldings to calibrated shifts with intervals."""
    if not model.get("usable"):
        return {"status": "abstained", "abstention": model.get("abstention"), "provenance": model["provenance"]}
    x = np.asarray(shieldings, dtype=float)
    if x.ndim != 1 or x.size == 0 or not np.isfinite(x).all():
        raise ValueError("A finite one-dimensional shielding vector is required")
    shifts = model["scaling"]["intercept"] + model["scaling"]["slope"] * x
    half, group = _interval_for(model, int(x.size))
    if half is None:
        return {"status": "abstained", "provenance": model["provenance"],
                "abstention": {"reason": "no_calibration_at_this_molecule_size",
                               "assigned_nuclei": int(x.size),
                               "calibrated_sizes": [[g["min_nuclei"], g["max_nuclei"]]
                                                    for g in model.get("size_conditional_groups") or []],
                               "detail": "The corpus contains no molecule of this size, so no interval "
                                         "at this size has coverage."}}
    outside = _domain_flags(model, x)
    result = {
        "status": "predicted",
        "fingerprint": model["fingerprint"],
        "provenance": model["provenance"],
        "target_coverage": model["target_coverage"],
        "predicted_shifts_ppm": shifts.tolist(),
        "interval_half_width_ppm": half,
        "intervals_ppm": [[float(s - half), float(s + half)] for s in shifts],
        "interval_scope": "simultaneous over all listed nuclei of this molecule",
        "size_group": group,
        "nucleus_diagnostic_half_width_ppm": model["nucleus_interval_ppm"],
        "atom_symbols": atom_symbols,
        "extrapolated_nucleus_indices": outside,
        "warnings": list(model["warnings"]),
    }
    if outside:
        result["warnings"].append(
            "Nuclei " + str(outside) + " have shieldings outside the fitted calibration range. "
            "Exchangeability with the calibration set is doubtful there and the stated coverage may not hold."
        )
    return result


def assess_identity(model, shieldings, observed_shifts, alpha=None):
    """Test whether a measured spectrum is consistent with a candidate structure.

    The nonconformity score is the molecule-level maximum absolute residual, the
    same statistic the calibration scores were built from. A conformal p-value
    below alpha means the candidate is rejected at that level. A p-value above
    alpha is not evidence the structure is correct; it only means the spectrum
    does not contradict it at this resolution.
    """
    if not model.get("usable"):
        return {"verdict": "abstained", "abstention": model.get("abstention"), "provenance": model["provenance"]}
    a = model["alpha"] if alpha is None else alpha
    x = np.asarray(shieldings, dtype=float)
    y = np.asarray(observed_shifts, dtype=float)
    if x.shape != y.shape or x.ndim != 1 or x.size == 0:
        raise ValueError("Shieldings and observed shifts must be matched one-dimensional arrays")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("Finite values required")
    residual = np.abs(y - (model["scaling"]["intercept"] + model["scaling"]["slope"] * x))
    score = float(residual.max())
    half, group = _interval_for(model, int(x.size))
    if half is None and model.get("size_conditional"):
        return {"verdict": "abstained", "provenance": model["provenance"],
                "abstention": {"reason": "no_calibration_at_this_molecule_size",
                               "assigned_nuclei": int(x.size)}}
    pool = model["calibration_scores_ppm"]
    if group is not None:
        sizes = model.get("calibration_score_sizes") or []
        if len(sizes) == len(pool):
            pool = [v for v, n in zip(pool, sizes) if group["min_nuclei"] <= n <= group["max_nuclei"]] or pool
    p = conformal_pvalue(pool, score)
    outside = _domain_flags(model, x)
    verdict = "inconsistent" if p <= a else "not_contradicted"
    out = {
        "verdict": verdict,
        "conformal_p_value": p,
        "alpha": a,
        "molecule_score_ppm": score,
        "worst_nucleus_index": int(np.argmax(residual)),
        "residuals_ppm": residual.tolist(),
        "calibration_molecules": model["split"]["calibration_molecules"],
        "size_group": group,
        "fingerprint": model["fingerprint"],
        "provenance": model["provenance"],
        "interpretation": "A rejection is a calibrated statement at the stated level. Absence of rejection is not confirmation of identity, purity or novelty.",
        "warnings": list(model["warnings"]),
    }
    if outside:
        out["verdict"] = "abstained"
        out["abstention"] = {
            "reason": "outside_calibration_domain",
            "nucleus_indices": outside,
            "detail": "Computed shieldings fall outside the fitted calibration range, so the calibration set does not support a claim about this molecule.",
        }
    return out
