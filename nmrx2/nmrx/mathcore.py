"""Unit-explicit physical transformations and experimental evidence diagnostics."""
import numpy as np
from scipy.constants import physical_constants, c, atomic_mass
EH = physical_constants['Hartree energy'][0]
BOHR = physical_constants['Bohr radius'][0]

def boltzmann(energies_kcal_mol, temperature=298.15):
    e = np.asarray(energies_kcal_mol, dtype=float)
    if e.ndim != 1 or not e.size or not np.isfinite(e).all() or not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("Finite energy vector and positive temperature required")
    w = np.exp(-(e-e.min()) / (0.00198720425864083 * temperature))
    return w/w.sum()

def ensemble(values, energies_kcal_mol, temperature=298.15):
    x = np.asarray(values, dtype=float); w = boltzmann(energies_kcal_mol, temperature)
    if x.ndim != 2 or len(x) != len(w) or not np.isfinite(x).all(): raise ValueError("Invalid ensemble")
    mean = w @ x
    return {"mean": mean.tolist(), "conformer_sd": np.sqrt(w @ ((x-mean)**2)).tolist(), "weights": w.tolist(),
            "warning": "Conformer dispersion is not prediction uncertainty; energies must share a method and environment"}

def normal_modes(hessian, xyz_bohr, masses_amu):
    """Remove rigid translation/rotation using an SVD before diagonalization."""
    xyz = np.asarray(xyz_bohr); masses = np.asarray(masses_amu)
    n = len(masses); root = np.sqrt(masses)
    centered = xyz - np.average(xyz, axis=0, weights=masses)
    rigid = []
    for axis in np.eye(3): rigid.append((root[:, None] * np.tile(axis, (n, 1))).ravel())
    for axis in np.eye(3): rigid.append((root[:, None] * np.cross(centered, axis)).ravel())
    u, s, _ = np.linalg.svd(np.array(rigid).T, full_matrices=True)
    rank = int(np.sum(s > s[0] * 1e-8)); vib = u[:, rank:]
    h = np.asarray(hessian); mass = np.repeat(root, 3)
    mw = ((h+h.T)/2) / np.outer(mass, mass)
    eigen, vectors = np.linalg.eigh(vib.T @ mw @ vib)
    factor = np.sqrt(EH / (BOHR**2 * atomic_mass)) / (2*np.pi*c*100)
    frequencies = np.sign(eigen) * np.sqrt(np.abs(eigen)) * factor
    cart_modes = (vib @ vectors) / mass[:, None]
    return frequencies, cart_modes, rank

def evidence_score(observed, predicted, sigma):
    """Experimental NMRx diagnostic, not a calibrated identity probability."""
    y,p,s = map(lambda x: np.asarray(x, dtype=float), (observed,predicted,sigma))
    if y.ndim != 1 or len(y)<2 or y.shape != p.shape or y.shape != s.shape or not all(np.isfinite(x).all() for x in (y,p,s)) or np.any(s<=0):
        raise ValueError("Matched finite arrays and positive uncertainty required")
    z = (y-p)/s
    # Student-t, nu=4: robust to occasional assignment/noise outliers.
    loss = float(np.mean(2.5*np.log1p(z*z/4)))
    return {"rmse": float(np.sqrt(np.mean((y-p)**2))), "mae": float(np.mean(abs(y-p))),
            "standardized_residuals": z.tolist(), "robust_loss": loss,
            "experimental_compatibility": float(np.exp(-loss)),
            "interpretation": "Descriptive fit index only. Not identity probability, novelty proof, or synthesis validation."}
