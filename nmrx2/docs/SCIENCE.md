# Scientific design

## Schrödinger equation and orbitals

In atomic units, the nonrelativistic clamped-nuclei electronic Hamiltonian is

\[
\hat H_e=-\frac12\sum_i\nabla_i^2-\sum_{iA}\frac{Z_A}{r_{iA}}+\sum_{i<j}\frac1{r_{ij}},\qquad \hat H_e\Psi=E_e\Psi.
\]

Total energy includes nuclear repulsion. General many-electron molecules do not have tractable exact analytic solutions. PySCF solves an approximate RHF or Kohn–Sham finite-basis SCF problem, \(FC=SC\epsilon\). HOMO and LUMO are the largest occupied and smallest unoccupied orbital eigenvalues. Their difference is not generally an optical gap, experimental excitation energy, or redox potential. No new Hamiltonian or functional is claimed.

## NMR

Shielding is a mixed energy response to magnetic field and nuclear moment, using the engine's sign convention. GIAO treats gauge-origin dependence.

\[
\sigma_{A,iso}=\operatorname{tr}(\boldsymbol\sigma_A)/3,\qquad
\delta_A\approx\sigma_{ref,A}-\sigma_{A,iso}.
\]

Reference method, basis, geometry protocol and environment must match. Atom indices refer to explicit-hydrogen RDKit ordering. Null shifts mean no reference was supplied. Solvent, temperature, exchange, spin coupling and assignments are not solved by this expression.

The properties extension supplies shielding operators. `quantum.py` adds a batch-compatible standard induced-potential map: modern Krylov solvers can pass fewer than three vectors, whereas the extension assumes three. Coupled response remains enabled. This compatibility adjustment is not new NMR physics and needs broad regression validation.

## IR

Central differences of analytic gradients form the Hessian:

\[
H_{ij}\approx[g_i(R+h e_j)-g_i(R-h e_j)]/(2h).
\]

After symmetrization and mass weighting, an SVD projects out rigid translation and rotation. Normally this removes six modes for nonlinear molecules, five for linear molecules. For vibrational eigenvalues expressed using Hartree, Bohr and atomic mass units:

\[
\tilde\nu_k=\frac{\operatorname{sign}(\lambda_k)}{2\pi c\,100}
\sqrt{|\lambda_k|E_h/(a_0^2m_u)}.
\]

Here c is in m/s and output is cm^-1. Negative values denote imaginary modes. Dipole derivatives use the same finite differences; intensities are proportional to squared dipole change along each mass-weighted normal coordinate, normalized to the maximum. They are not absolute km/mol. Step size, grid, basis and residual-gradient sensitivity remain necessary accuracy checks.

## Conformer utility

For compatible conformer free energies in kcal/mol:

\[
w_c=\frac{e^{-(G_c-G_{min})/(RT)}}{\sum_j e^{-(G_j-G_{min})/(RT)}},\qquad \bar y=\sum_cw_cy_c.
\]

The Python utility returns weighted mean and conformer dispersion. Dispersion is not total predictive uncertainty. MMFF energies are not solution-phase free energies. Automatic per-conformer QM/thermochemistry is future work.

## Experimental compatibility diagnostic

For explicitly matched measurements y, predictions p and independently justified positive standard deviations s:

\[
z_i=(y_i-p_i)/s_i,\quad L=\frac1n\sum_i\frac52\log(1+z_i^2/4),\quad C=e^{-L}.
\]

This uses a standard Student-t-shaped robust loss with four degrees of freedom. It is **not proven novel mathematics**, a probability of identity, or a confidence level. It satisfies 0<C<=1; perfect agreement gives 1 and increasing an absolute standardized residual decreases C, directly from monotonicity of log and nonnegative summands.

Inflating s artificially improves the score. Fit uncertainties on separate calibration data and freeze them. Do not compare scores indiscriminately across nuclei, assignment coverage or modalities. Correlated errors and post-hoc peak matching further preclude probability interpretations.

A research proposal for NMRx is joint assignment/conformer/solvent inference with calibrated abstention and expected-information selection of the next experiment. It requires prior-art review, a specified probabilistic model, identifiability work, scaffold-separated data and baseline comparisons. It is not represented as implemented or novel here.

## Validation program before scientific claims

1. Compare analytic and finite-difference Hessians, test rotation/translation invariance, response residuals, reference consistency and step/grid/basis convergence.
2. Benchmark assigned 1H/13C spectra and IR on held-out scaffold-separated molecules with known solvent/temperature. Include protonation, tautomer and out-of-domain challenges.
3. Report per-nucleus MAE/RMSE, unmatched-peak penalties, uncertainty interval coverage, calibration, runtime and cost.
4. For docking, use prepared co-crystals, symmetry-aware heavy-atom redocking RMSD, ligand strain/clashes, multiple seeds/receptors, and active/decoy enrichment.
5. A computed spectrum does not prove synthesis, identity, purity, efficacy or stability. No universal accuracy claim is established.

Primary sources: [PySCF DFT](https://pyscf.org/user/dft.html), [geometry optimization](https://pyscf.org/user/geomopt.html), [properties extension](https://github.com/pyscf/properties), [Vina Python documentation](https://autodock-vina.readthedocs.io/en/latest/docking_python.html).
