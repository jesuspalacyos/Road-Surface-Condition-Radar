"""Sensor validation, experimental road features and durable recording. Standard library only."""
import json, math, sqlite3, threading, time, uuid
from collections import deque
from statistics import median

SERVICE = '7b9e0001-6b47-4a4d-8e73-61942c1d7600'
TELEMETRY = '7b9e0002-6b47-4a4d-8e73-61942c1d7600'
CONTROL = '7b9e0003-6b47-4a4d-8e73-61942c1d7600'

def number(v, lo=-1e9, hi=1e9):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and lo <= v <= hi

def normalize(d):
    # Explicit units: ToF mm, acceleration g, GPS decimal degrees / km/h.
    if d.get('schema') != 'road-v1':
        raise ValueError('Expected schema road-v1; use bundled firmware or adapt normalize()')
    out = {k: d.get(k) if number(d.get(k),lo,hi) else None for k,lo,hi in
           [('tof_mm',20,2000),('ax',-16,16),('ay',-16,16),('az',-16,16),
            ('lat',-90,90),('lon',-180,180),('speed_kmh',0,350),('satellites',0,100)]}
    out['gps_fix'] = d.get('gps_fix') is True and out['lat'] is not None and out['lon'] is not None
    if not out['gps_fix']:
        out['lat']=out['lon']=out['speed_kmh']=None
    return out

class Store:
    def __init__(self, path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, session TEXT, ts REAL, kind TEXT, payload TEXT, upload INTEGER, synced INTEGER DEFAULT 0)')
        self.db.commit()
    def add(self,session,kind,payload,upload):
        with self.lock:
            self.db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,0)',(uuid.uuid4().hex,session,time.time(),kind,json.dumps(payload,allow_nan=False),int(upload)))
            self.db.commit()
    def pending(self, limit=20):
        with self.lock:
            return self.db.execute('SELECT id, session, ts, kind, payload FROM records WHERE upload=1 AND synced=0 ORDER BY ts LIMIT ?', (limit,)).fetchall()
    def sessions(self):
        with self.lock:
            rows=self.db.execute("SELECT session,min(ts),max(ts),count(*),sum(kind='event'),sum(upload=1 AND synced=0) FROM records GROUP BY session ORDER BY min(ts) DESC LIMIT 100").fetchall()
            return [dict(zip(('session','start','end','records','events','pending'),r)) for r in rows]
    def history(self,session,limit=5000):
        with self.lock:
            rows=self.db.execute('SELECT ts,kind,payload FROM records WHERE session=? ORDER BY ts DESC LIMIT ?', (session,limit)).fetchall()
            return [{'time':ts,'kind':kind,'data':json.loads(payload)} for ts,kind,payload in reversed(rows)]
    def csv_rows(self,session):
        # Export one selected trip, including every saved sample.
        with self.lock:
            rows=self.db.execute('SELECT ts,session,kind,payload,synced FROM records WHERE session=? ORDER BY ts',(session,)).fetchall()
        return rows
    def mark(self,ids):
        with self.lock:
            self.db.executemany('UPDATE records SET synced=1 WHERE id=?',[(i,) for i in ids]); self.db.commit()
    def counts(self):
        with self.lock:
            return self.db.execute('SELECT count(*), coalesce(sum(upload=1 AND synced=0),0) FROM records').fetchone()

class Monitor:
    def __init__(self,config,store,demo=False):
        self.c=config; self.store=store; self.demo=demo; self.lock=threading.RLock()
        self.sensor={}; self.sensor_at=0; self.radar={}; self.radar_at=0
        self.baseline=None; self.calibration=[]; self.calibrating=False
        self.session=None; self.recording=False; self.last_snapshot=0
        self.events=deque(maxlen=8); self.last_event=0; self.candidate=None; self.run=0
        self.cloud={'enabled':False,'last_sync':None,'error':None}
        self.errors={}; self.message='Connect sensors, then calibrate on a flat surface.'
    def command(self,cmd):
        with self.lock:
            if cmd=='start':
                if not self.recording:
                    self.session=uuid.uuid4().hex; self.recording=True; self.last_snapshot=0
                    self.store.add(self.session,'session_start',{'demo':self.demo},not self.demo)
                self.message='Recording on Pi. Cloud samples are queued.'
            elif cmd=='stop':
                if self.recording: self.store.add(self.session,'session_stop',{'demo':self.demo},not self.demo)
                self.recording=False; self.message='Recording stopped. Saved data stays on Pi.'
            elif cmd=='calibrate':
                self.baseline=None; self.calibration=[]; self.calibrating=True
                self.message='Keep sensor still over flat road: collecting 30 valid readings.'
            else: raise ValueError('Unknown command')
    def set_radar(self,frame):
        with self.lock:
            pts=frame['points']; c=self.c
            roi=[p for p in pts if abs(p[0])<=c['radar_half_width_m'] and c['radar_near_m']<=p[1]<=c['radar_far_m'] and c['radar_z_min_m']<=p[2]<=c['radar_z_max_m']]
            heights=[]
            if c.get('radar_mount_height_m') is not None and c.get('radar_pitch_down_deg') is not None:
                angle=math.radians(c['radar_pitch_down_deg'])
                heights=[p[2]*math.cos(angle)-p[1]*math.sin(angle)+c['radar_mount_height_m'] for p in roi]
            self.radar={'frame':frame['frame'],'points':len(pts),'road_points':len(roi),
                        'height_mm':round(median(heights)*1000,1) if len(heights)>=3 else None,
                        'range_power_mean':frame.get('range_power_mean')}
            self.radar_at=time.monotonic(); self.errors.pop('radar',None)
    def ingest(self,d):
        s=normalize(d); now=time.monotonic()
        with self.lock:
            self.sensor=s; self.sensor_at=now; self.errors.pop('sensor',None)
            axis=self.c['vertical_axis']; acc=s.get(axis)
            if self.calibrating and s['tof_mm'] is not None and acc is not None:
                self.calibration.append((s['tof_mm'],acc))
                if len(self.calibration)>=30:
                    tof=[v[0] for v in self.calibration]; a=[v[1] for v in self.calibration]
                    if max(tof)-min(tof)>20 or max(a)-min(a)>0.15:
                        self.calibration=[]; self.message='Calibration moved too much; hold still and try again.'
                    else:
                        self.baseline=(median(tof),median(a)); self.calibrating=False
                        self.message='Calibrated. Road alerts are experimental candidates.'
            depth=None; shock=None; kind=None
            if self.baseline:
                depth=s['tof_mm']-self.baseline[0] if s['tof_mm'] is not None else None
                shock=abs(acc-self.baseline[1]) if acc is not None else None
                if depth is not None and depth>=self.c['depth_mm']: kind='Possible pothole'
                elif depth is not None and depth<=-self.c['raised_mm']: kind='Possible raised object'
                elif shock is not None and shock>=self.c['shock_g']: kind='Rough road / bump'
            s['depth_mm']=round(depth,1) if depth is not None else None
            s['shock_g']=round(shock,3) if shock is not None else None
            self.run=self.run+1 if kind and self.candidate==kind else (1 if kind else 0)
            self.candidate=kind
            if kind and self.run>=self.c['persistence_samples'] and now-self.last_event>=self.c['event_cooldown_s']:
                h=self.radar.get('height_mm') if now-self.radar_at<2 else None
                supported=(kind=='Possible pothole' and h is not None and h<=-self.c['depth_mm']) or (kind=='Possible raised object' and h is not None and h>=self.c['raised_mm'])
                event={'time':time.time(),'label':kind,'depth_mm':s['depth_mm'],'lat':s['lat'],'lon':s['lon'],
                       'evidence':'ToF + experimental radar geometry' if supported else 'ToF' if depth is not None and abs(depth)>=min(self.c['depth_mm'],self.c['raised_mm']) else 'Accelerometer',
                       'verified':False,'demo':self.demo}
                self.events.appendleft(event); self.last_event=now
                if self.recording: self.store.add(self.session,'event',event,not self.demo)
            if self.recording:
                upload=now-self.last_snapshot>=self.c['cloud_snapshot_s']
                self.store.add(self.session,'sample',{'sensor':s.copy(),'radar':self.radar.copy() if now-self.radar_at<2 else None,'ice':'unverified','demo':self.demo},upload and not self.demo)
                if upload:self.last_snapshot=now
    def snapshot(self):
        with self.lock:
            now=time.monotonic(); total,pending=self.store.counts()
            return {'demo':self.demo,'time':time.time(),'sensor':self.sensor.copy(),'sensor_fresh':now-self.sensor_at<2,
                    'radar':self.radar.copy(),'radar_fresh':now-self.radar_at<2,'calibrated':self.baseline is not None,
                    'calibrating':self.calibrating,'recording':self.recording,'session':self.session,
                    'events':list(self.events)[:3],'cloud':dict(self.cloud,pending=pending),'saved':total,
                    'current_alert':self.candidate if now-self.sensor_at<2 and self.run>=self.c['persistence_samples'] else None,
                    'message':self.message,'errors':self.errors.copy(),'ice':'unverified'}
