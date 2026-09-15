import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from nmrx.api import app
from nmrx.calibration import (build, predict, assess_identity, fit_scaling,
                              conformal_quantile, conformal_pvalue, minimum_calibration_size)

TRUE_INTERCEPT, TRUE_SLOPE = 31.0, -1.02
PROVENANCE = {'method': 'B3LYP', 'basis': 'def2-tzvp', 'nucleus': '1H',
              'solvent': 'CDCl3', 'reference_compound': 'TMS'}

def molecule(rng, ident, nuclei=None, offset=0.0, span=(22.0, 32.0)):
    """Synthetic record with a molecule-level offset, so nuclei are correlated."""
    nuclei = nuclei or int(rng.integers(2, 9))
    sigma = rng.uniform(*span, size=nuclei)
    shift = TRUE_INTERCEPT + TRUE_SLOPE*sigma + rng.normal(0, 0.10) + rng.normal(0, 0.12, size=nuclei)
    if offset: shift[0] += offset
    return {'id': ident, 'nuclei': [{'index': int(i), 'shielding_ppm': float(s), 'observed_shift_ppm': float(d)}
                                    for i, (s, d) in enumerate(zip(sigma, shift))]}

def corpus(seed=1, count=80, **kw):
    rng = np.random.default_rng(seed)
    return {'provenance': PROVENANCE, 'records': [molecule(rng, 'm%d' % i, **kw) for i in range(count)]}

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NMRX_DB', str(tmp_path/'jobs.db'))
    monkeypatch.setenv('NMRX_API_KEYS', json.dumps({'a': 'a'*32, 'b': 'b'*32}))
    return TestClient(app)

def test_minimum_calibration_size_matches_quantile_feasibility():
    for alpha in (0.05, 0.1, 0.2):
        need = minimum_calibration_size(alpha)
        assert not conformal_quantile(np.zeros(need-1), alpha)[2]
        assert conformal_quantile(np.zeros(need), alpha)[2]
    assert minimum_calibration_size(0.05) == 19

def test_quantile_is_infinite_rather_than_optimistic():
    q, k, ok = conformal_quantile(np.arange(10.0), 0.05)
    assert not ok and q == float('inf') and k == 11

def test_pvalue_is_uniform_under_the_null():
    rng = np.random.default_rng(0)
    scores = rng.normal(size=200)**2
    p = [conformal_pvalue(scores, rng.normal()**2) for _ in range(4000)]
    assert 0.03 < np.mean(np.array(p) <= 0.05) < 0.075

def test_scaling_recovers_the_generating_line():
    fit = build(corpus(), alpha=0.05)['scaling']
    assert abs(fit['slope'] - TRUE_SLOPE) < 0.02
    assert abs(fit['intercept'] - TRUE_INTERCEPT) < 0.5
    assert fit['r_squared'] > 0.99
    assert 'warning' not in fit

def test_positive_slope_is_flagged():
    assert 'warning' in fit_scaling([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])

def test_small_set_abstains_and_states_the_required_size():
    model = build(corpus(count=20), alpha=0.05)
    assert not model['usable'] and model['molecule_interval_ppm'] is None
    assert model['abstention']['reason'] == 'calibration_split_too_small'
    assert model['abstention']['required_calibration_molecules'] == 19
    assert predict(model, [25.0])['status'] == 'abstained'
    assert assess_identity(model, [25.0], [5.0])['verdict'] == 'abstained'

def test_usable_model_reports_a_finite_simultaneous_interval():
    model = build(corpus(count=200), alpha=0.05)
    assert model['usable'] and 0 < model['molecule_interval_ppm'] < 2
    out = predict(model, [24.0, 28.0], ['H', 'H'])
    assert out['status'] == 'predicted' and len(out['intervals_ppm']) == 2
    low, high = out['intervals_ppm'][0]
    assert low < out['predicted_shifts_ppm'][0] < high
    assert out['interval_scope'].startswith('simultaneous')

def test_empirical_simultaneous_coverage_meets_the_nominal_level():
    """The guarantee is the product. Verify it rather than assume it."""
    hit = []
    for seed in range(300):
        rng = np.random.default_rng(10_000 + seed)
        model = build({'provenance': PROVENANCE, 'records': [molecule(rng, 'm%d' % i) for i in range(240)]},
                      alpha=0.1, seed=seed)
        probe = molecule(rng, 'probe')
        sigma = [n['shielding_ppm'] for n in probe['nuclei']]
        observed = np.array([n['observed_shift_ppm'] for n in probe['nuclei']])
        out = predict(model, sigma)
        if out['status'] == 'abstained':
            continue          # coverage is claimed only where the model does not abstain
        bounds = np.array(out['intervals_ppm'])
        hit.append(bool(np.all((observed >= bounds[:, 0]) & (observed <= bounds[:, 1]))))
    assert len(hit) >= 200 and np.mean(hit) >= 0.87

def test_matching_spectrum_is_not_rejected_and_decoy_is():
    rng = np.random.default_rng(7)
    model = build(corpus(seed=7), alpha=0.05, seed=7)
    truth = molecule(rng, 'truth')
    sigma = [n['shielding_ppm'] for n in truth['nuclei']]
    observed = [n['observed_shift_ppm'] for n in truth['nuclei']]
    assert assess_identity(model, sigma, observed)['verdict'] == 'not_contradicted'
    decoy = list(observed); decoy[2] += 3.0
    verdict = assess_identity(model, sigma, decoy)
    assert verdict['verdict'] == 'inconsistent'
    assert verdict['conformal_p_value'] <= 0.05 and verdict['worst_nucleus_index'] == 2

def test_absence_of_rejection_is_never_stated_as_confirmation():
    model = build(corpus(count=200), alpha=0.05)
    out = assess_identity(model, [25.0, 26.0], [5.5, 4.4])
    assert out['verdict'] in ('not_contradicted', 'inconsistent', 'abstained')
    assert 'not confirmation' in out['interpretation']

def test_extrapolation_beyond_the_fitted_range_abstains():
    model = build(corpus(count=200), alpha=0.05)
    far = float(model['scaling']['shielding_range_ppm'][1]) + 40.0
    assert predict(model, [far, far])['extrapolated_nucleus_indices'] == [0, 1]
    out = assess_identity(model, [far, far], [0.0, 0.0])
    assert out['verdict'] == 'abstained' and out['abstention']['reason'] == 'outside_calibration_domain'

def test_mixed_provenance_is_refused():
    with pytest.raises(ValueError, match='provenance'):
        build({'provenance': {'method': 'B3LYP'}, 'records': corpus(count=40)['records']})

def test_split_is_deterministic_and_independent_of_submission_order():
    data = corpus(count=60)
    shuffled = {'provenance': PROVENANCE, 'records': list(reversed(data['records']))}
    assert build(data)['fingerprint'] == build(shuffled)['fingerprint']
    assert build(data)['molecule_interval_ppm'] == build(shuffled)['molecule_interval_ppm']

def test_endpoints_require_a_key(client):
    for route in ('/v1/calibration/fit', '/v1/calibration/shifts', '/v1/calibration/identity'):
        assert client.post(route, json={}).status_code in (401, 422)
    assert client.post('/v1/calibration/fit', json=corpus(count=40)).status_code == 401

def test_fit_endpoint_returns_a_usable_model(client):
    r = client.post('/v1/calibration/fit', json=corpus(), headers={'X-API-Key': 'a'*32})
    assert r.status_code == 200
    body = r.json()
    assert body['usable'] and body['target_coverage'] == 0.95
    assert body['provenance']['solvent'] == 'CDCl3'
    assert any('exchangeable' in w for w in body['warnings'])

def test_shifts_endpoint_returns_intervals(client):
    payload = {'calibration': corpus(count=200), 'isotropic_shielding_ppm': [24.0, 27.5],
               'atom_symbols': ['H', 'H']}
    body = client.post('/v1/calibration/shifts', json=payload, headers={'X-API-Key': 'a'*32}).json()
    assert body['status'] == 'predicted' and body['interval_half_width_ppm'] > 0

def test_identity_endpoint_abstains_on_a_short_corpus(client):
    payload = {'calibration': corpus(count=20), 'isotropic_shielding_ppm': [24.0],
               'observed_shift_ppm': [6.0]}
    body = client.post('/v1/calibration/identity', json=payload, headers={'X-API-Key': 'a'*32}).json()
    assert body['verdict'] == 'abstained'
    assert body['abstention']['required_total_molecules_at_this_split'] > 20

def test_identity_endpoint_rejects_unmatched_lengths(client):
    payload = {'calibration': corpus(count=40), 'isotropic_shielding_ppm': [24.0, 25.0],
               'observed_shift_ppm': [6.0]}
    assert client.post('/v1/calibration/identity', json=payload, headers={'X-API-Key': 'a'*32}).status_code == 422

def test_duplicate_record_ids_rejected(client):
    data = corpus(count=40); data['records'][1]['id'] = data['records'][0]['id']
    assert client.post('/v1/calibration/fit', json=data, headers={'X-API-Key': 'a'*32}).status_code == 422


def test_size_conditional_groups_cover_the_corpus_size_range():
    """A molecule-level maximum grows with the count it is taken over."""
    model = build(corpus(count=400), alpha=0.05)
    groups = model['size_conditional_groups']
    assert model['size_conditional'] and len(groups) >= 2
    assert all(g['calibration_molecules'] >= 19 for g in groups)
    assert all(g['usable'] and g['interval_ppm'] > 0 for g in groups)
    assert [g['min_nuclei'] for g in groups] == sorted(g['min_nuclei'] for g in groups)
    # Bins are contiguous and between them cover every size the corpus contains,
    # so no size inside the observed range silently falls through to an abstention.
    covered = {n for g in groups for n in range(g['min_nuclei'], g['max_nuclei'] + 1)}
    assert covered == set(range(min(covered), max(covered) + 1))
    assert covered.issuperset(set(model['calibration_score_sizes']))


def test_a_size_the_corpus_never_saw_abstains_rather_than_borrowing_a_band():
    rng = np.random.default_rng(2)
    records = [molecule(rng, 'm%d' % i, nuclei=4) for i in range(120)]
    model = build({'provenance': PROVENANCE, 'records': records}, alpha=0.05)
    assert predict(model, [25.0] * 4)['status'] == 'predicted'
    out = predict(model, [25.0] * 30)
    assert out['status'] == 'abstained'
    assert out['abstention']['reason'] == 'no_calibration_at_this_molecule_size'
    assert assess_identity(model, [25.0] * 30, [5.0] * 30)['verdict'] == 'abstained'


def test_size_conditioning_improves_coverage_for_the_largest_molecules():
    """Regression guard for the defect this was added to fix."""
    rng = np.random.default_rng(21)
    pooled_hits, grouped_hits = [], []
    for seed in range(60):
        records = [molecule(rng, 'm%d' % i) for i in range(260)]
        model = build({'provenance': PROVENANCE, 'records': records}, alpha=0.1, seed=seed)
        probe = molecule(rng, 'probe', nuclei=8)
        sigma = [n['shielding_ppm'] for n in probe['nuclei']]
        observed = np.array([n['observed_shift_ppm'] for n in probe['nuclei']])
        bounds = np.array(predict(model, sigma)['intervals_ppm'])
        grouped_hits.append(bool(np.all((observed >= bounds[:, 0]) & (observed <= bounds[:, 1]))))
        pooled = model['molecule_interval_ppm']
        centre = model['scaling']['intercept'] + model['scaling']['slope'] * np.asarray(sigma)
        pooled_hits.append(bool(np.all(np.abs(observed - centre) <= pooled)))
    assert np.mean(grouped_hits) >= np.mean(pooled_hits)
