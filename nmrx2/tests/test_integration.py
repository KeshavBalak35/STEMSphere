import json
import pytest
from nmrx import store
from nmrx.worker import run_one
from nmrx.guide import answer

def test_worker_real_job(tmp_path,monkeypatch):
    pytest.importorskip('pyscf')
    monkeypatch.setenv('NMRX_DB',str(tmp_path/'jobs.db'))
    ident=store.submit('a','quantum',{'smiles':'O','task':'orbitals','method':'HF','basis':'sto-3g','optimize':False,'conformers':1})
    assert run_one()
    r=store.fetch('a',ident)
    assert r['status']=='succeeded'
    assert r['result']['provenance']['input_sha256']==r['input_hash']

def test_ai_payload_and_extraction(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    monkeypatch.setenv('NMRX_AI_MODEL','test-model')
    import httpx
    class Client:
        def __init__(self,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,headers,json):
            assert json['store'] is False
            assert 'SECRET_STRUCTURE' not in json['input']
            return httpx.Response(200,request=httpx.Request('POST',url),json={'output':[{'type':'message','content':[{'type':'output_text','text':'Interpretation test'}]}]})
    monkeypatch.setattr('nmrx.guide.httpx.Client',Client)
    r=answer('Explain',{'status':'succeeded','result':{'poses_pdbqt':'SECRET_STRUCTURE','homo_ev':-7}},True)
    assert r['answer']=='Interpretation test'

def test_real_docking_smoke():
    pytest.importorskip('vina'); pytest.importorskip('meeko')
    from nmrx.docking import calculate
    receptor='ATOM      1  C   ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C\n'
    r=calculate({'smiles':'CCO','receptor_pdbqt':receptor,'center_angstrom':[0,0,0],
       'box_angstrom':[10,10,10],'conformers':1,'exhaustiveness':1,'poses':1,
       'preparation_notes':'Synthetic single atom connectivity test only'})
    assert r['scores_kcal_mol'] and 'MODEL' in r['poses_pdbqt']
