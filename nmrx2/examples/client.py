"""Minimal Python client; configure NMRX_CLIENT_KEY before running."""
import os,time,httpx
with httpx.Client(base_url=os.getenv('NMRX_URL','http://127.0.0.1:8000'),headers={'X-API-Key':os.environ['NMRX_CLIENT_KEY']},timeout=30) as c:
    r=c.post('/v1/jobs/quantum',json={'smiles':'O','task':'orbitals','method':'HF','basis':'sto-3g'})
    r.raise_for_status(); ident=r.json()['id']
    for _ in range(1000):
        response=c.get('/v1/jobs/'+ident); response.raise_for_status(); job=response.json()
        if job['status'] in ('succeeded','failed'):
            print(job); break
        time.sleep(2)
    else: raise TimeoutError('Polling stopped; the server job may still be running')
