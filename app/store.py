import sqlite3, json, os
from pathlib import Path
from app.errors import DomainError
def connection():
    path=Path(os.environ.get('APP_DB','data/runs.sqlite3'));path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30);db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=30000')
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    db.execute('''CREATE TABLE IF NOT EXISTS releases(
        id TEXT PRIMARY KEY, batch TEXT NOT NULL UNIQUE, grade TEXT NOT NULL,
        run_id TEXT NOT NULL, order_id TEXT NOT NULL, idem_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL)''')
    return db
def save(result):
    with connection() as db:
        ident=result['manifest']['run_id'];row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
        if row: return {**json.loads(row['payload']), 'revision':row['revision'], 'decision':row['decision'], 'reused':True}
        db.execute('INSERT INTO runs(id,payload) VALUES (?,?)',(ident,json.dumps(result,ensure_ascii=False)))
    return {**result,'revision':1,'decision':'待复核','reused':False}
def get_run(ident):
    with connection() as db: row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
    if row is None: raise DomainError('NOT_FOUND','批次不存在',404)
    return {**json.loads(row['payload']),'revision':row['revision'],'decision':row['decision']}
def latest():
    with connection() as db: row=db.execute('SELECT payload,revision,decision FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
    return {**json.loads(row['payload']),'revision':row['revision'],'decision':row['decision']} if row else None
def history():
    with connection() as db: return [dict(r) for r in db.execute('SELECT id,revision,decision FROM runs ORDER BY rowid DESC')]
def review(ident, revision, decision):
    if decision not in ('通过','退回'): raise DomainError('DECISION','复核动作无效')
    with connection() as db:
        changed=db.execute('UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?',(decision,ident,revision)).rowcount
        if not changed: raise DomainError('VERSION','版本已变化，请重新载入',409)
    return {'revision':revision+1,'decision':decision}
def create_release(form):
    """同一炉次仅一份放行单；同幂等键重试返回原单，不新增。"""
    import uuid
    from datetime import datetime, timezone
    fields=('batch','grade','run_id','order_id','idem_key')
    for name in fields:
        if not str(form.get(name) or '').strip(): raise DomainError('RELEASE','放行单缺少字段：'+name)
    ident=uuid.uuid4().hex
    created=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    values=(ident,form['batch'].strip(),form['grade'].strip(),form['run_id'].strip(),
            form['order_id'].strip(),form['idem_key'].strip(),created)
    with connection() as db:
        existing=db.execute('SELECT * FROM releases WHERE idem_key=?',(form['idem_key'],)).fetchone()
        if existing:
            if existing['batch']!=form['batch'].strip() or existing['grade']!=form['grade'].strip():
                raise DomainError('IDEMPOTENT','幂等键已用于不同的放行请求',409)
            return dict(existing)
        try:
            db.execute('INSERT INTO releases(id,batch,grade,run_id,order_id,idem_key,created_at) VALUES (?,?,?,?,?,?,?)',values)
        except sqlite3.IntegrityError:
            winner=db.execute('SELECT * FROM releases WHERE batch=?',(form['batch'].strip(),)).fetchone()
            raise DomainError('RELEASE_CONFLICT',
                '炉次'+form['batch'].strip()+'已存在放行单（'+winner['grade']+'，'+winner['id']+'），不能重复放行',409)
    with connection() as db:
        return dict(db.execute('SELECT * FROM releases WHERE id=?',(ident,)).fetchone())
def list_releases(batch=None):
    with connection() as db:
        if batch:
            return [dict(r) for r in db.execute('SELECT * FROM releases WHERE batch=? ORDER BY created_at',(batch,))]
        return [dict(r) for r in db.execute('SELECT * FROM releases ORDER BY created_at')]
