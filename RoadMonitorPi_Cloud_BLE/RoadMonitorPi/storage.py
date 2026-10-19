"""Durable local history/outbox. Remote writes use stable IDs for safe retry."""
import json, sqlite3, threading, time, uuid

class Store:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, payload TEXT, synced INTEGER DEFAULT 0)')
        self.db.commit()
        self.enabled=False; self.error=None; self.last_sync=None
    def put(self,kind,payload):
        ident=uuid.uuid4().hex
        with self.lock:
            self.db.execute('INSERT INTO records VALUES (?,?,?,0)',(ident,kind,json.dumps(payload,allow_nan=False)))
            self.db.commit()
        return ident
    def pending(self,limit=25):
        with self.lock:
            return self.db.execute('SELECT id,kind,payload FROM records WHERE synced=0 ORDER BY rowid LIMIT ?',(limit,)).fetchall()
    def ack(self,ident):
        with self.lock:
            self.db.execute('UPDATE records SET synced=1 WHERE id=?',(ident,));self.db.commit()
            self.last_sync=time.time()
    def events(self,limit=None):
        sql="SELECT payload FROM records WHERE kind='event' ORDER BY rowid DESC"
        with self.lock:
            rows=self.db.execute(sql+(' LIMIT ?' if limit is not None else ''),(limit,) if limit is not None else ()).fetchall()
        return [json.loads(r[0]) for r in rows]
    def status(self):
        with self.lock:
            pending=self.db.execute('SELECT count(*) FROM records WHERE synced=0').fetchone()[0]
        return {'cloud_enabled':self.enabled,'pending':pending,'last_sync':self.last_sync,'error':self.error,'local':'SQLite + raw JSONL'}

def sync_once(store,db,cfg):
    for ident,kind,raw in store.pending():
        doc=db.collection(cfg['cloud_collection']).document(cfg['cloud_device_id']).collection('events' if kind=='event' else 'samples').document(ident)
        doc.set(json.loads(raw),timeout=15)
        store.ack(ident)

def cloud_loop(store,cfg):
    store.enabled=True; db=None; backoff=2
    while True:
        try:
            if db is None:
                import firebase_admin
                from firebase_admin import firestore
                try:app=firebase_admin.get_app()
                except ValueError:app=firebase_admin.initialize_app()
                db=firestore.client(app=app)
            sync_once(store,db,cfg)
            store.error=None;backoff=2
            time.sleep(2)
        except Exception as exc:
            store.error=type(exc).__name__+': '+str(exc)
            time.sleep(backoff);backoff=min(60,backoff*2)
