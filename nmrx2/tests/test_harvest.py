import json
import numpy as np
import pytest
from rdkit import Chem

from nmrx.calibration import build
from nmrx.harvest import (SOURCES, SPECTRAL_AND_CLEAR, deduplicate, normalize_solvent,
                          pending_quantum_jobs, quality_filter, required_total, stratify,
                          to_calibration_set)
from nmrx.harvest.cli import main
from nmrx.harvest.nmrshiftdb import detect_index_base, load, parse_peaks

TRUE_INTERCEPT, TRUE_SLOPE = 186.0, -1.0   # 13C-like shielding to shift map


def record(ident, shifts, nucleus='13C', solvent='CDCl3', reference=None, smiles=None, **kw):
    return dict({'id': ident, 'smiles': smiles or 'C' * (len(shifts) + 1), 'inchikey': ident,
                 'nucleus': nucleus, 'solvent': solvent, 'reference_compound': reference,
                 'field_mhz': 400.0, 'predicted': False,
                 'nuclei': [{'atom_index': i, 'observed_shift_ppm': s, 'element': 'C'}
                            for i, s in enumerate(shifts)]}, **kw)


def test_licence_registry_is_explicit_about_closed_sources():
    assert SOURCES['sdbs']['commercial_use'] == 'prohibited'
    assert SOURCES['sdbs']['bulk_download_allowed'] is False
    assert SOURCES['nist_webbook']['bulk_download_allowed'] is False
    assert SOURCES['nmrshiftdb2']['commercial_use'] == 'share_alike'
    assert SOURCES['drugbank']['commercial_use'] == 'restricted'
    assert all(s['verified'] is False for s in SOURCES.values())


def test_largest_open_spectral_source_is_not_commercially_clear():
    """The share-alike question is a business fact, not a footnote."""
    assert 'nmrshiftdb2' not in SPECTRAL_AND_CLEAR


def test_parse_peaks_tolerates_format_variants():
    assert parse_peaks('12.5;0.0;1|30.2;0.0;2|') == [
        {'observed_shift_ppm': 12.5, 'atom_index': 1, 'multiplicity': None},
        {'observed_shift_ppm': 30.2, 'atom_index': 2, 'multiplicity': None}]
    fused = parse_peaks('54.4;0.0Q;3;')
    assert fused[0]['observed_shift_ppm'] == 54.4
    assert parse_peaks('') == [] and parse_peaks('garbage') == []


def test_index_base_detection_refuses_to_guess():
    assert detect_index_base([0, 1, 2], 3) == 0
    assert detect_index_base([1, 2, 3], 3) == 1
    assert detect_index_base([1, 2], 4) is None       # fits either convention
    assert detect_index_base([9], 3) is None          # fits neither


def test_solvent_normalisation_returns_none_rather_than_guessing():
    assert normalize_solvent('Chloroform-D1') == 'CDCl3'
    assert normalize_solvent('DMSO') == 'DMSO-d6'
    assert normalize_solvent('unknown') is None
    assert normalize_solvent(None) is None


def test_quality_filter_drops_impossible_and_predicted_values():
    records = [record('a', [30.0, 40.0]),
               record('b', [30.0, 9999.0]),
               record('c', [30.0, 40.0], solvent=None),
               record('d', [30.0, 40.0], predicted=True),
               record('e', [30.0, 40.0], nucleus='1H')]
    kept, rejected = quality_filter(records, nucleus='13C', min_nuclei=2)
    assert [k['id'] for k in kept] == ['a']
    assert rejected['missing_solvent'] == 1 and rejected['predicted_not_measured'] == 1
    assert rejected['wrong_nucleus'] == 1 and rejected['too_few_usable_assignments'] == 1


def test_deduplicate_keeps_one_record_per_molecule_and_slice():
    a, b = record('x', [30.0, 40.0]), record('x', [30.0, 40.0, 50.0])
    assert len(deduplicate([a, b])) == 1
    assert len(deduplicate([a, b])[0]['nuclei']) == 3


def test_required_corpus_size_accounts_for_the_training_split():
    assert required_total(0.05, 0.5) == 39
    assert required_total(0.10, 0.5) == 19
    assert required_total(0.05, 0.75) > required_total(0.05, 0.5)


def test_stratification_does_not_merge_incompatible_slices():
    rng = np.random.default_rng(3)
    records = ([record('cdcl3-%d' % i, list(rng.uniform(10, 150, 4))) for i in range(30)] +
               [record('dmso-%d' % i, list(rng.uniform(10, 150, 4)), solvent='DMSO-d6') for i in range(30)])
    summary = stratify(records, alpha=0.05)
    assert summary['total_slices'] == 2
    assert summary['usable_slices'] == 0          # 30 each, 39 needed, and they cannot be pooled
    assert summary['molecules_stranded_below_threshold'] == 60
    assert all(s['shortfall'] == 9 for s in summary['slices'])


def test_corpus_assembly_refuses_to_silently_drop_missing_shieldings():
    records = [record('a', [30.0]), record('b', [40.0])]
    with pytest.raises(ValueError, match='pending_quantum_jobs'):
        to_calibration_set(records, {'a': [100.0]}, {})


def test_pending_jobs_are_one_per_distinct_structure():
    records = [record('a', [30.0], smiles='CCO'), record('b', [31.0], smiles='CCO'),
               record('c', [32.0], smiles='CCC')]
    jobs = pending_quantum_jobs(records, basis='def2-tzvp')
    assert len(jobs) == 2 and jobs[0]['task'] == 'nmr' and jobs[0]['basis'] == 'def2-tzvp'


def test_harvest_output_feeds_the_calibration_layer_end_to_end():
    """The only integration that matters: harvested shape produces a usable model."""
    rng = np.random.default_rng(11)
    records, shieldings = [], {}
    for i in range(45):
        sigma = rng.uniform(20.0, 170.0, size=5)
        shift = TRUE_INTERCEPT + TRUE_SLOPE * sigma + rng.normal(0, 0.4) + rng.normal(0, 0.8, size=5)
        ident = 'mol%d' % i
        records.append(record(ident, shift.tolist(), smiles='C%d' % i))
        shieldings[ident] = sigma.tolist()
    corpus = to_calibration_set(records, shieldings,
                                {'method': 'B3LYP', 'basis': 'def2-tzvp', 'nucleus': '13C',
                                 'solvent': 'CDCl3', 'reference_compound': 'TMS'})
    assert len(corpus['records']) == 45
    model = build(corpus, alpha=0.05)
    assert model['usable']
    assert abs(model['scaling']['slope'] - TRUE_SLOPE) < 0.05
    assert 0 < model['molecule_interval_ppm'] < 8


def _write_sdf(path, entries):
    writer = Chem.SDWriter(str(path))
    for name, smiles, props, add_h in entries:
        mol = Chem.MolFromSmiles(smiles)
        if add_h:
            mol = Chem.AddHs(mol)
        mol.SetProp('_Name', name)
        for key, value in props.items():
            mol.SetProp(key, str(value))
        writer.write(mol)
    writer.close()


def test_sdf_round_trip_recovers_assignments_and_solvent(tmp_path):
    path = tmp_path / 'mini.sdf'
    _write_sdf(path, [('nsd1', 'CCO', {'Spectrum 13C 0': '58.4;0.0;0|18.2;0.0;1|',
                                       'Solvent': 'Chloroform-D1'}, False)])
    records = load(path)
    assert len(records) == 1
    got = records[0]
    assert got['nucleus'] == '13C' and got['solvent'] == 'CDCl3'
    assert got['unusable_reason'] is None and got['index_base_detected'] == 0
    assert [n['observed_shift_ppm'] for n in got['nuclei']] == [58.4, 18.2]
    assert [n['element'] for n in got['nuclei']] == ['C', 'C']
    assert got['reference_compound'] is None       # never assumed to be TMS
    assert got['licence'].startswith('CC BY-SA')


def test_proton_assignments_without_explicit_hydrogens_are_marked_unusable(tmp_path):
    path = tmp_path / 'h.sdf'
    _write_sdf(path, [('nsd2', 'CCO', {'Spectrum 1H 0': '3.7;0.0;0|1.2;0.0;1|',
                                       'Solvent': 'CDCl3'}, False)])
    assert load(path)[0]['unusable_reason'] == 'implicit_hydrogens_cannot_be_indexed'


def test_cli_ingest_reports_stratification(tmp_path, capsys):
    path = tmp_path / 'many.sdf'
    rng = np.random.default_rng(5)
    entries = []
    for i in range(12):
        peaks = '|'.join('%.1f;0.0;%d' % (rng.uniform(10, 160), j) for j in range(2))
        entries.append(('n%d' % i, 'CC' + 'O' * (i % 3 + 1), {'Spectrum 13C 0': peaks, 'Solvent': 'CDCl3'}, False))
    _write_sdf(path, entries)
    out = tmp_path / 'records.json'
    assert main(['ingest', str(path), '--nucleus', '13C', '--min-nuclei', '2', '--out', str(out)]) == 0
    text = capsys.readouterr().out
    assert '39 molecules required per corpus' in text
    assert 'short by' in text
    assert json.loads(out.read_text())['stratification']['usable_slices'] == 0


def test_cli_jobs_counts_distinct_structures(tmp_path, capsys):
    path = tmp_path / 'records.json'
    path.write_text(json.dumps({'records': [record('a', [30.0], smiles='CCO'),
                                            record('b', [31.0], smiles='CCC')]}))
    assert main(['jobs', str(path)]) == 0
    assert '2 distinct structures need a quantum NMR job' in capsys.readouterr().out


def test_cli_sources_lists_the_registry(capsys):
    assert main(['sources']) == 0
    assert 'prohibited' in capsys.readouterr().out
