"""Single-job child process. Receives JSON on stdin; writes only machine output to file."""
import contextlib, importlib.metadata, json, sys
from . import __version__

def execute(kind,payload):
    if kind=='quantum':
        from .quantum import calculate
        return calculate(payload)
    if kind=='docking':
        from .docking import calculate
        return calculate(payload)
    raise ValueError('Unsupported job type')

if __name__=='__main__':
    req=json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        result=execute(req['kind'],req['payload'])
    versions={}
    for name in ['numpy','scipy','rdkit','pyscf','geometric','vina','meeko','pyscf-properties']:
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: pass
    result['provenance']={'nmrx_version':__version__,'dependencies':versions,'input':req['payload'] if req['kind']=='quantum' else {k:v for k,v in req['payload'].items() if k!='receptor_pdbqt'}}
    with open(sys.argv[1],'w') as out: json.dump(result,out,allow_nan=False)
