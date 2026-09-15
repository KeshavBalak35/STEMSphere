import csv
import gzip
import os
from pathlib import Path

import numpy as np
import pytest
from rdkit import Chem

from nmrx.calibration import build, predict
from nmrx.harvest import SOURCES
from nmrx.harvest.cascade import (PROVENANCE, SELECTION_WARNING, load_records, summary,
                                  to_calibration_set)

CACHE = os.getenv('NMRX_CASCADE_CACHE')


def _write(directory, molecules):
    """Build a miniature CASCADE layout: Exp5K, DFT8K and the NMR8K metadata SDF."""
    directory = Path(directory)
    for name, rows in (('Exp5K.csv.gz', 'observed'), ('DFT8K.csv.gz', 'computed')):
        with gzip.open(directory / name, 'wt', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['', 'mol_id', 'atom_index', 'Shift', 'atom_type']
                            if rows == 'observed' else ['', 'mol_id', 'atom_type', 'atom_index', 'Shift'])
            n = 0
            for mol_id, _, values in molecules:
                for index, (obs, comp) in enumerate(values):
                    value = obs if rows == 'observed' else comp
                    writer.writerow([n, mol_id, index, value, 6] if rows == 'observed'
                                    else [n, mol_id, 6, index, value])
                    n += 1
    writer_sdf = Chem.SDWriter(str(directory / 'NMR8K.sdf'))
    for mol_id, smiles, values in molecules:
        mol = Chem.MolFromSmiles(smiles)
        mol.SetProp('_Name', mol_id)
        mol.SetProp('nmrshiftdb2 ID', mol_id)
        mol.SetProp('Solvent', '0:Chloroform-D1 (CDCl3)')
        mol.SetProp('Spectrum 13C 0', '|'.join('%.1f;0.0;%d' % (v[0], i) for i, v in enumerate(values)))
        writer_sdf.write(mol)
    writer_sdf.close()
    with open(directory / 'NMR8K.sdf', 'rb') as src, gzip.open(directory / 'NMR8K.sdf.gz', 'wb') as out:
        out.write(src.read())
    (directory / 'NMR8K.sdf').unlink()


@pytest.fixture
def mini(tmp_path):
    rng = np.random.default_rng(0)
    molecules = []
    for i in range(60):
        computed = rng.uniform(15.0, 160.0, size=4)
        observed = computed + rng.normal(0, 0.3) + rng.normal(0, 0.8, size=4)
        molecules.append(('%d' % i, 'CCCC', list(zip(observed.round(2), computed.round(4)))))
    _write(tmp_path, molecules)
    return tmp_path


def test_records_pair_observed_with_computed(mini):
    records = load_records(mini)
    assert len(records) == 60
    assert all(len(r['nuclei']) == 4 for r in records)
    first = records[0]['nuclei'][0]
    assert 'observed_shift_ppm' in first and 'computed_shift_ppm' in first
    assert records[0]['solvent'] == 'CDCl3'
    assert records[0]['id'].startswith('cascade:')


def test_min_nuclei_is_enforced(mini):
    assert load_records(mini, min_nuclei=5) == []


def test_every_corpus_carries_the_selection_warning(mini):
    records = load_records(mini)
    assert 'filtered' in SELECTION_WARNING or 'agreeing' in SELECTION_WARNING
    assert to_calibration_set(records)['selection_warning'] == SELECTION_WARNING
    assert summary(records)['selection_warning'] == SELECTION_WARNING


def test_licence_records_both_layers(mini):
    """The MIT repository licence does not settle the NMRShiftDB terms beneath it."""
    licence = load_records(mini)[0]['licence']
    assert 'MIT' in licence and 'CC BY-SA' in licence
    assert SOURCES['cascade']['commercial_use'] == 'share_alike'


def test_provenance_declares_a_computed_shift_not_a_shielding(mini):
    corpus = to_calibration_set(load_records(mini), solvent='CDCl3')
    assert corpus['provenance']['computed_kind'] == 'shift'
    model = build(corpus, alpha=0.05, computed_kind='shift')
    assert model['usable'] and model['scaling']['slope'] > 0
    assert 'warning' not in model['scaling']        # positive slope is correct for a shift


def test_solvent_filter_selects_one_slice(mini):
    records = load_records(mini)
    assert len(to_calibration_set(records, solvent='CDCl3')['records']) == 60
    assert to_calibration_set(records, solvent='DMSO-d6')['records'] == []


@pytest.mark.skipif(not CACHE, reason='set NMRX_CASCADE_CACHE to run against the real download')
def test_real_corpus_calibrates_and_covers():
    records = load_records(CACHE)
    assert len(records) > 4000
    model = build(to_calibration_set(records), alpha=0.05, computed_kind='shift')
    assert model['usable'] and model['size_conditional']
    assert 0.9 < model['scaling']['slope'] < 1.1
    assert model['scaling']['r_squared'] > 0.99
    assert 3.0 < model['molecule_interval_ppm'] < 8.0
    probe = records[0]
    out = predict(model, [n['computed_shift_ppm'] for n in probe['nuclei']])
    assert out['status'] == 'predicted'
    observed = np.array([n['observed_shift_ppm'] for n in probe['nuclei']])
    bounds = np.array(out['intervals_ppm'])
    assert np.all((observed >= bounds[:, 0]) & (observed <= bounds[:, 1]))
    assert out['size_group']['min_nuclei'] <= len(probe['nuclei']) <= out['size_group']['max_nuclei']
