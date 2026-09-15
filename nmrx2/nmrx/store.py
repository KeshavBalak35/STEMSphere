import hashlib, json, os, sqlite3, time, uuid
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def connect():
    path=Path(os.getenv('NMRX_DB','data/jobs.sqlite3')); path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=30); c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT, payload TEXT, status TEXT, result TEXT, error TEXT, created REAL, updated REAL, input_hash TEXT)')
    try:
        with c:
            yield c
    finally:
        c.close()

def submit(owner,kind,payload):
    packed=json.dumps(payload,sort_keys=True,allow_nan=False)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        pending=c.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running')",(owner,)).fetchone()[0]
        total=c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        if pending >= 10 or total >= 100: raise ValueError('Job queue quota reached')
        ident=str(uuid.uuid4()); now=time.time()
        c.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,owner,kind,packed,'queued',None,None,now,now,hashlib.sha256(packed.encode()).hexdigest()))
    return ident

def fetch(owner,ident):
    with connect() as c: row=c.execute('SELECT * FROM jobs WHERE id=? AND owner=?',(ident,owner)).fetchone()
    if row is None: return None
    d=dict(row); d.pop('owner'); d.pop('payload')
    d['result']=json.loads(d['result']) if d['result'] else None
    return d

def claim():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE jobs SET status='running', updated=? WHERE id=?",(time.time(),row['id']))
            return dict(row)

def finish(ident,result=None,error=None):
    with connect() as c:
        c.execute("UPDATE jobs SET status=?,result=?,error=?,updated=? WHERE id=? AND status='running'",
                  ('failed' if error else 'succeeded',json.dumps(result,allow_nan=False) if result is not None else None,error,time.time(),ident))
