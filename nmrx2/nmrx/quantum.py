import importlib.metadata
import numpy as np
from .chemistry import prepare
from .mathcore import normal_modes

EV_PER_HARTREE = 27.211386245981

def calculate(payload):
    from pyscf import gto, scf, dft, lib
    from .models import Quantum
    req = Quantum.model_validate(payload)
    # Some container PID namespaces expose /proc without the process's own PID.
    # Use conservative peak RSS for the engine's memory heuristic in that case.
    try:
        lib.current_memory()
    except FileNotFoundError:
        import resource
        def peak_memory():
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            return rss_mb, rss_mb
        lib.current_memory = peak_memory
    lib.num_threads(1)
    rd, cid, prep = prepare(req.smiles, req.conformers, req.seed)
    coords = prep['coordinates_angstrom']; symbols = prep['atom_symbols']
    mol = gto.M(atom=list(zip(symbols, coords)), unit='Angstrom', basis=req.basis,
                charge=prep['charge'], spin=0, verbose=0, max_memory=1500)
    if mol.nelectron % 2: raise ValueError('Closed-shell even-electron molecules only')
    def solve(m):
        mf = scf.RHF(m) if req.method == 'HF' else dft.RKS(m)
        if req.method != 'HF':
            mf.xc = req.method; mf.grids.level = 3
            # Properties extension sizes its integration blocks from grid size.
            # Pad grid with zero-weight points to the native integration block.
            mf.grids.alignment = dft.numint.BLKSIZE
        mf.conv_tol = 1e-10; mf.max_cycle = 100
        mf.kernel()
        if not mf.converged: raise ValueError('SCF did not converge; no prediction returned')
        return mf
    mf = solve(mol)
    if req.optimize:
        # geomeTRIC is an optional extra. Import it only when an optimization is
        # actually requested, so a deployment without it can still run single-point
        # jobs instead of failing at import time.
        try:
            from pyscf.geomopt.geometric_solver import kernel as optimize_kernel
        except ImportError as exc:
            raise RuntimeError('Geometry optimization requires the separately installed '
                               'geomeTRIC package; submit optimize=false to run a single point') from exc
        converged, mol = optimize_kernel(mf, maxsteps=100)
        if not converged: raise ValueError('Geometry optimization failed to converge')
        mf = solve(mol)
    grad = mf.nuc_grad_method().kernel()
    occupied = np.asarray(mf.mo_occ)>0; eps = np.asarray(mf.mo_energy)
    if not occupied.any() or occupied.all(): raise ValueError('No occupied/virtual orbital pair in chosen basis')
    homo = float(max(eps[occupied])*EV_PER_HARTREE); lumo = float(min(eps[~occupied])*EV_PER_HARTREE)
    result = {"preparation": prep, "method": req.method, "basis": req.basis, "environment": "gas phase",
        "engine": "PySCF", "engine_version": importlib.metadata.version('pyscf'),
        "energy_hartree": float(mf.e_tot), "homo_ev": homo, "lumo_ev": lumo, "orbital_gap_ev": lumo-homo,
        "orbital_energies_ev": (eps*EV_PER_HARTREE).tolist(), "occupations": mf.mo_occ.tolist(),
        "coordinates_angstrom": mol.atom_coords(unit='Angstrom').tolist(),
        "gradient_max_hartree_bohr": float(abs(grad).max()), "scf_converged": True,
        "warnings": prep['warnings'] + ['Orbital gap is not an optical gap or measured redox potential',
        'Single selected conformer; gas-phase calculation; no solvent or temperature correction',
        'SCF convergence does not establish wavefunction stability or global geometry minimum']}
    if req.task == 'nmr':
        try:
            from pyscf.prop.nmr import rhf, rks
        except ImportError as exc:
            raise RuntimeError('NMR requires the separately installed pyscf-properties extension; see README') from exc
        nmr = rhf.NMR(mf) if req.method == 'HF' else rks.NMR(mf)
        nmr.gauge_orig = None  # GIAO, origin-independent basis treatment
        # pyscf-properties assumes exactly three Krylov vectors. Modern PySCF
        # can reduce that batch rank. Supply the same response map with dynamic
        # batch dimensions, without disabling the coupled response equations.
        coeff = mf.mo_coeff; occ_coeff = coeff[:, mf.mo_occ > 0]
        response = mf.gen_response(singlet=True, hermi=2)
        def induced(mo1):
            amplitudes = np.asarray(mo1).reshape(-1, coeff.shape[1], occ_coeff.shape[1])
            density = 2 * np.einsum('pi,xij,qj->xpq', coeff, amplitudes, occ_coeff.conj())
            density = density - density.transpose(0, 2, 1).conj()
            potential = response(density)
            return np.einsum('pi,xpq,qj->xij', coeff.conj(), potential, occ_coeff).ravel()
        nmr.cphf = induced
        # RKS wrapper coerces a callable to bool; both allowed DFT methods are
        # hybrids, so use the shared coupled solver directly to retain the map.
        from types import MethodType
        nmr.solve_mo1 = MethodType(rhf.solve_mo1, nmr)
        nmr.conv_tol = 1e-9
        nmr.max_cycle_cphf = 100
        tensors = nmr.kernel()
        if not np.isfinite(tensors).all(): raise ValueError('Nonfinite NMR shielding tensor')
        iso = np.trace(tensors, axis1=1, axis2=2)/3
        shifts = [None if a not in req.reference_shielding_ppm else float(req.reference_shielding_ppm[a]-s) for a,s in zip(symbols,iso)]
        result['nmr'] = {'shielding_tensors_ppm': tensors.tolist(), 'isotropic_shielding_ppm': iso.tolist(),
                         'chemical_shifts_ppm': shifts, 'reference_provenance': req.reference_provenance,
                         'atom_index_base': 0, 'atom_symbols': symbols}
        result['warnings'].append('Shifts require same-level reference shieldings; coupling, exchange and full multiplets are not calculated')
    if req.task == 'ir':
        if abs(grad).max() > 5e-4: raise ValueError('Geometry gradient too large for vibrational analysis')
        xyz = mol.atom_coords(); n = xyz.size; step = req.displacement_bohr
        hess = np.zeros((n,n)); dipder = np.zeros((3,n))
        for k in range(n):
            gp=[]; dp=[]
            for sign in (1,-1):
                displaced = xyz.copy().ravel(); displaced[k] += sign*step
                m = mol.copy(); m.set_geom_(displaced.reshape(-1,3), unit='Bohr')
                f = solve(m); gp.append(f.nuc_grad_method().kernel().ravel())
                dp.append(np.asarray(f.dip_moment(unit='AU', verbose=0)))
            hess[:,k]=(gp[0]-gp[1])/(2*step); dipder[:,k]=(dp[0]-dp[1])/(2*step)
        masses = [a.GetMass() for a in rd.GetAtoms()]
        freqs,modes,rank = normal_modes(hess,xyz,masses)
        intensity = np.sum((dipder @ modes)**2,axis=0)
        relative = intensity/intensity.max() if intensity.size and intensity.max()>0 else intensity
        result['ir'] = {'frequencies_cm-1': freqs.tolist(), 'relative_intensities': relative.tolist(),
                        'rigid_mode_rank': rank, 'imaginary_modes_below_minus20': int(sum(freqs < -20)),
                        'displacement_bohr': step, 'hessian_asymmetry_max': float(abs(hess-hess.T).max()),
                        'intensity_units': 'normalized relative; not km/mol', 'frequency_scale_factor': 1.0}
        if np.any(freqs < -20): result['warnings'].append('Imaginary modes: geometry is not verified as a local minimum')
    return result
