import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from nmrx.api import app
from nmrx.mathcore import boltzmann, normal_modes, evidence_score
from nmrx.chemistry import prepare
from nmrx import store

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NMRX_DB',str(tmp_path/'jobs.db'))
    monkeypatch.setenv('NMRX_API_KEYS',json.dumps({'a':'a'*32,'b':'b'*32}))
    return TestClient(app)

def test_auth(client):
    assert client.post('/v1/molecules/validate',json={'smiles':'O'}).status_code==401

def test_validation_and_stereo(client):
    r=client.post('/v1/molecules/validate',headers={'x-api-key':'a'*32},json={'smiles':'CC(O)F'})
    assert r.status_code==200
    assert any('stereocenters' in x for x in r.json()['warnings'])

@pytest.mark.parametrize('smiles',['not smiles','[Na+].[Cl-]','[Fe]','[CH3]'])
def test_invalid_chemistry(smiles):
    with pytest.raises(ValueError): prepare(smiles)

def test_weights():
    assert np.allclose(boltzmann([0,0]),[0.5,0.5])
    assert np.isclose(boltzmann([10000,10001]).sum(),1)
    with pytest.raises(ValueError): boltzmann([0],0)

def test_fit():
    good=evidence_score([1,2],[1,2],[1,1]); bad=evidence_score([1,2],[5,7],[1,1])
    assert good['experimental_compatibility']==1
    assert bad['experimental_compatibility']<good['experimental_compatibility']

def test_linear_modes():
    # Analytic two-mass spring: one vibrational mode, five rigid modes.
    h=np.zeros((6,6)); h[0,0]=h[3,3]=1; h[0,3]=h[3,0]=-1
    f,q,rank=normal_modes(h,[[-1,0,0],[1,0,0]],[1,1])
    assert rank==5 and len(f)==1 and f[0]>0
    assert np.isclose(np.sum(q[:,0]**2),1)

def test_tenant_isolation_and_claim(client):
    r=client.post('/v1/jobs/quantum',headers={'x-api-key':'a'*32},json={'smiles':'O','task':'orbitals','optimize':False})
    assert r.status_code==202
    ident=r.json()['id']
    assert client.get('/v1/jobs/'+ident,headers={'x-api-key':'b'*32}).status_code==404
    assert store.claim()['id']==ident
    assert store.claim() is None
    store.finish(ident,result={'ok':True})
    assert client.get('/v1/jobs/'+ident,headers={'x-api-key':'a'*32}).json()['status']=='succeeded'

def test_numeric_and_reference_validation(client):
    hdr={'x-api-key':'a'*32}
    assert client.post('/v1/validation/spectral-fit',headers=hdr,json={'observed':[1,2],'predicted':[1,2],'sigma':[0,1],'modality':'nmr_ppm','assignment_provenance':'manual'}).status_code==422
    assert client.post('/v1/jobs/quantum',headers=hdr,json={'smiles':'O','task':'nmr','reference_shielding_ppm':{'H':31}}).status_code==422

def test_local_guide(client):
    r=client.post('/v1/guide',headers={'x-api-key':'a'*32},json={'question':'What should I calculate?'})
    assert r.json()['external_data_sent'] is False
