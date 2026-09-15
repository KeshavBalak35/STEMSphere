import json, os, subprocess, sys, tempfile, time, logging
from pathlib import Path
from .store import claim, finish
logging.basicConfig(level=logging.INFO)

def run_one():
    job=claim()
    if job is None: return False
    with tempfile.TemporaryDirectory() as d:
        dest=Path(d)/'result.json'
        # Child receives only compute-related environment; no API credentials.
        env={k:v for k,v in os.environ.items() if k in ('PATH','PYTHONPATH','LD_LIBRARY_PATH','HOME','VIRTUAL_ENV')}
        env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        try:
            with open(Path(d)/'engine.log','w+') as log:
                p=subprocess.run([sys.executable,'-m','nmrx.runner',str(dest)],
                    input=json.dumps({'kind':job['kind'],'payload':json.loads(job['payload'])}),
                    text=True,stdout=log,stderr=log,env=env,timeout=int(os.getenv('NMRX_JOB_TIMEOUT','1800')))
                if p.returncode:
                    log.seek(0,2); size=log.tell(); log.seek(max(0,size-2000))
                    logging.error('Job %s failed: %s',job['id'],log.read())
                    finish(job['id'],error='Engine failed. Operator should inspect worker logs; no valid result produced.')
                else:
                    result=json.loads(dest.read_text()); result['provenance']['input_sha256']=job['input_hash']
                    finish(job['id'],result=result)
        except subprocess.TimeoutExpired:
            finish(job['id'],error='Compute time limit exceeded')
        except Exception:
            logging.exception('Worker error for %s',job['id']); finish(job['id'],error='Worker execution failed')
    return True

if __name__=='__main__':
    while True:
        if not run_one(): time.sleep(1)
