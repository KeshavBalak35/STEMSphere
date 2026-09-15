import pytest
pytest.importorskip('pyscf')
from nmrx.quantum import calculate

def test_real_water_hf():
    r=calculate({'smiles':'O','method':'HF','basis':'sto-3g','optimize':False,'conformers':1})
    assert r['scf_converged']
    assert -75.1<r['energy_hartree']<-74.8
    assert r['homo_ev']<r['lumo_ev']
    assert len(r['occupations'])==7

def test_real_water_ir():
    r=calculate({'smiles':'O','task':'ir','method':'HF','basis':'sto-3g','conformers':1})
    ir=r['ir']
    assert len(ir['frequencies_cm-1'])==3
    assert ir['imaginary_modes_below_minus20']==0
    assert ir['hessian_asymmetry_max']<1e-3
    # Independent analytic PySCF Hessian/frequency comparison, same geometry.
    import numpy as np
    from pyscf import gto,scf
    from pyscf.hessian.thermo import harmonic_analysis
    m=gto.M(atom=list(zip(['O','H','H'],r['coordinates_angstrom'])),basis='sto-3g',verbose=0)
    mf=scf.RHF(m).run(conv_tol=1e-10)
    ref=harmonic_analysis(m,mf.Hessian().kernel())['freq_wavenumber'].real
    assert np.allclose(sorted(ref),sorted(ir['frequencies_cm-1']),atol=2)

@pytest.mark.parametrize('method',['HF','B3LYP'])
def test_real_water_nmr(method):
    pytest.importorskip('pyscf.prop.nmr')
    r=calculate({'smiles':'O','task':'nmr','method':method,'basis':'sto-3g','optimize':False,'conformers':1})
    s=r['nmr']['isotropic_shielding_ppm']
    assert len(s)==3 and abs(s[1]-s[2])<0.05
    assert 15<s[1]<50
    assert r['nmr']['chemical_shifts_ppm']==[None,None,None]
