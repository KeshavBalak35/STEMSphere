import tempfile
from pathlib import Path
import numpy as np
from .chemistry import prepare
from .models import Docking

def calculate(payload):
    from vina import Vina
    from meeko import MoleculePreparation, PDBQTWriterLegacy
    req = Docking.model_validate(payload)
    lines = req.receptor_pdbqt.splitlines()
    atom_lines = [x for x in lines if x.startswith(('ATOM  ', 'HETATM'))]
    if not atom_lines or any(x.startswith(('ROOT', 'BRANCH', 'TORSDOF')) for x in lines):
        raise ValueError('A prepared rigid receptor PDBQT is required')
    try: xyz = np.array([[float(x[30:38]),float(x[38:46]),float(x[46:54])] for x in atom_lines])
    except ValueError as exc: raise ValueError('Invalid receptor coordinates') from exc
    if not np.isfinite(xyz).all(): raise ValueError('Nonfinite receptor coordinates')
    center=np.array(req.center_angstrom); half=np.array(req.box_angstrom)/2
    if not np.any(np.all(abs(xyz-center)<=half,axis=1)): raise ValueError('Docking box contains no receptor atoms')
    mol,cid,prep=prepare(req.smiles,req.conformers,req.seed)
    conf = mol.GetConformer(cid)
    from rdkit import Chem
    conf = Chem.Conformer(conf); mol.RemoveAllConformers(); mol.AddConformer(conf, assignId=True)
    setups=MoleculePreparation().prepare(mol)
    if len(setups)!=1: raise ValueError('Expected exactly one prepared ligand setup')
    ligand,ok,error=PDBQTWriterLegacy.write_string(setups[0])
    if not ok: raise ValueError('Ligand PDBQT preparation failed: '+error)
    with tempfile.TemporaryDirectory() as temp:
        receptor=Path(temp)/'receptor.pdbqt'; receptor.write_text(req.receptor_pdbqt)
        v=Vina(sf_name='vina',cpu=1,seed=req.seed,verbosity=0)
        v.set_receptor(str(receptor)); v.set_ligand_from_string(ligand)
        v.compute_vina_maps(center=list(req.center_angstrom),box_size=list(req.box_angstrom))
        v.dock(exhaustiveness=req.exhaustiveness,n_poses=req.poses)
        energies=v.energies(n_poses=req.poses)
        poses=v.poses(n_poses=req.poses)
    if not len(energies) or not np.isfinite(energies).all(): raise ValueError('No finite docking poses')
    return {'preparation':prep,'engine':'AutoDock Vina','scores_kcal_mol':energies[:,0].tolist(),
            'poses_pdbqt':poses,'center_angstrom':req.center_angstrom,'box_angstrom':req.box_angstrom,
            'receptor_preparation_notes':req.preparation_notes,
            'warnings':['Docking scores are heuristic rankings, not experimental binding free energies or efficacy',
                        'Rigid receptor; no covalent docking, metal-specific scoring, or water/protonation sampling',
                        'Receptor biological assembly, missing residues and charges require external preparation',
                        'Pose contacts/clashes and enrichment/redocking benchmarks remain required before conclusions']}
