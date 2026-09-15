import hashlib, hmac, json, os
from fastapi import FastAPI, Depends, Header, HTTPException
from .models import Molecule, Quantum, Docking, Evidence, Guide, CalibrationSet, CalibratedShifts, IdentityCheck
from .chemistry import prepare
from .mathcore import evidence_score
from . import store
from .guide import answer
from . import calibration

app=FastAPI(title='NMRx 2.0 Research Backend',version='0.1.0')

@app.middleware('http')
async def body_limit(request,call_next):
    # Enforce actual streamed size, including chunked requests.
    size=0; chunks=[]
    async for chunk in request.stream():
        size+=len(chunk)
        if size>2200000:
            from starlette.responses import JSONResponse
            return JSONResponse({'detail':'Request too large'},status_code=413)
        chunks.append(chunk)
    request._body=b''.join(chunks)
    return await call_next(request)

def owner(x_api_key: str = Header(default='')):
    try: keys=json.loads(os.getenv('NMRX_API_KEYS','{}'))
    except ValueError: raise HTTPException(503,'API keys are not configured correctly')
    if not keys: raise HTTPException(503,'Configure NMRX_API_KEYS before using the API')
    for tenant,key in keys.items():
        if isinstance(key,str) and len(key)>=24 and hmac.compare_digest(x_api_key,key): return tenant
    raise HTTPException(401,'Invalid API key')

@app.get('/health')
def health(): return {'status':'ok','release':'research alpha'}

@app.post('/v1/molecules/validate')
def validate(req:Molecule,tenant=Depends(owner)):
    try: return prepare(req.smiles,req.conformers,req.seed)[2]
    except ValueError as exc: raise HTTPException(422,str(exc))

def enqueue(tenant,kind,req):
    try:
        # Fail fast on invalid chemical input before queueing.
        prep=prepare(req.smiles,1,req.seed)[2]
        if kind=='quantum' and req.task=='ir' and len(prep['atom_symbols'])>30:
            raise ValueError('Finite-difference IR limited to 30 atoms including hydrogens')
        ident=store.submit(tenant,kind,req.model_dump())
        return {'id':ident,'status':'queued','poll_url':'/v1/jobs/'+ident}
    except ValueError as exc: raise HTTPException(422,str(exc))

@app.post('/v1/jobs/quantum',status_code=202)
def quantum(req:Quantum,tenant=Depends(owner)): return enqueue(tenant,'quantum',req)

@app.post('/v1/jobs/docking',status_code=202)
def docking(req:Docking,tenant=Depends(owner)): return enqueue(tenant,'docking',req)

@app.get('/v1/jobs/{ident}')
def job(ident:str,tenant=Depends(owner)):
    result=store.fetch(tenant,ident)
    if result is None: raise HTTPException(404,'Job not found')
    return result

@app.post('/v1/validation/spectral-fit')
def fit(req:Evidence,tenant=Depends(owner)):
    return dict(evidence_score(req.observed,req.predicted,req.sigma),modality=req.modality,assignment_provenance=req.assignment_provenance)

@app.post('/v1/guide')
def guide(req:Guide,tenant=Depends(owner)):
    context=job(req.job_id,tenant) if req.job_id else None
    try: return answer(req.question,context,req.use_external_ai)
    except ValueError as exc: raise HTTPException(503,str(exc))
    except Exception: raise HTTPException(502,'AI provider request failed')

def _model(req):
    try:
        return calibration.build(req.model_dump(exclude={'alpha','train_fraction','seed'}),
                                 alpha=req.alpha, train_fraction=req.train_fraction, seed=req.seed)
    except ValueError as exc: raise HTTPException(422,str(exc))

@app.post('/v1/calibration/fit')
def calibration_fit(req:CalibrationSet,tenant=Depends(owner)):
    """Fit scaling and conformal quantiles for one method-matched reference set."""
    return _model(req)

@app.post('/v1/calibration/shifts')
def calibration_shifts(req:CalibratedShifts,tenant=Depends(owner)):
    """Convert computed shieldings to calibrated shifts with coverage intervals."""
    try: return calibration.predict(_model(req.calibration),req.isotropic_shielding_ppm,req.atom_symbols)
    except ValueError as exc: raise HTTPException(422,str(exc))

@app.post('/v1/calibration/identity')
def calibration_identity(req:IdentityCheck,tenant=Depends(owner)):
    """Test a measured spectrum against a candidate structure, or abstain."""
    try: return calibration.assess_identity(_model(req.calibration),req.isotropic_shielding_ppm,req.observed_shift_ppm)
    except ValueError as exc: raise HTTPException(422,str(exc))
