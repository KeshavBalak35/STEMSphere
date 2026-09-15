import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors

ALLOWED = {1, 6, 7, 8, 9, 14, 15, 16, 17, 35}

def prepare(smiles, conformers=5, seed=42):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError("Invalid SMILES or valence")
    if len(Chem.GetMolFrags(mol)) != 1:
        raise ValueError("Submit one connected molecule; define salts and protonation explicitly")
    if any(a.GetAtomicNum() not in ALLOWED for a in mol.GetAtoms()):
        raise ValueError("Initial release supports H,C,N,O,F,Si,P,S,Cl,Br only")
    if any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        raise ValueError("Radicals/open-shell molecules are outside this release's validated domain")
    warnings = []
    if any(s == '?' for _, s in Chem.FindMolChiralCenters(mol, includeUnassigned=True)):
        warnings.append("Unspecified stereocenters: submitted structure does not identify one stereoisomer")
    mol = Chem.AddHs(mol)
    if mol.GetNumAtoms() > 80:
        raise ValueError("Maximum 80 atoms including hydrogens")
    p = AllChem.ETKDGv3(); p.randomSeed = seed; p.pruneRmsThresh = 0.3
    ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=conformers, params=p))
    if not ids:
        raise ValueError("3D embedding failed")
    if not AllChem.MMFFHasAllMoleculeParams(mol):
        raise ValueError("MMFF parameters unavailable; use a specialist preparation workflow")
    fits = AllChem.MMFFOptimizeMoleculeConfs(mol, maxIters=1000, numThreads=1)
    valid = [(cid, float(e)) for cid, (status, e) in zip(ids, fits) if status == 0]
    if not valid:
        raise ValueError("No force-field conformer converged")
    cid, energy = min(valid, key=lambda x: x[1])
    if len(valid) != len(ids): warnings.append("Some MMFF conformers did not converge and were excluded")
    xyz = np.asarray(mol.GetConformer(cid).GetPositions())
    dist = np.linalg.norm(xyz[:, None] - xyz[None, :], axis=2)
    np.fill_diagonal(dist, np.inf)
    if dist.min() < 0.55: raise ValueError("Unphysical atom overlap after embedding")
    atoms = [a.GetSymbol() for a in mol.GetAtoms()]
    return mol, cid, {
        "canonical_smiles": Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True),
        "formula": rdMolDescriptors.CalcMolFormula(mol), "molecular_weight": Descriptors.MolWt(mol),
        "charge": Chem.GetFormalCharge(mol), "atom_symbols": atoms,
        "coordinates_angstrom": xyz.tolist(), "selected_conformer_id": cid,
        "conformers": [{"id": i, "mmff_energy_kcal_mol": e} for i, e in valid],
        "warnings": warnings + ["MMFF selection is not a thermodynamic conformer ensemble; protonation and tautomers were not enumerated"],
    }
