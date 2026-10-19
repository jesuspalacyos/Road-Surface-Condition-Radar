#!/usr/bin/env python3
"""Local Raspberry Pi road-monitor prototype. No trained road classifier."""
import argparse, csv, io, json, math, random, threading, time
from statistics import median
from storage import Store, cloud_loop
from ble_input import ble_loop
from pathlib import Path
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from radar import RadarParser
ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock()
def finite(v): return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def utc(): return datetime.now(timezone.utc).isoformat()
class Monitor:
    def __init__(self, cfg, demo=False, store=None):
        self.store=store; self.last_snapshot=0; self.ranges=[]; self.deep_count=0; self.raised_count=0; self.cleaned={}; self.transport="USB"
        self.cfg=cfg; self.demo=demo; self.sensor={}; self.radar={}; self.st=0; self.rt=0
        self.errors={}; self.baseline=None; self.cal=[]; self.calibrating=False
        self.events=store.events(500) if store else []; self.trace=[]; self.last_event={}; self.shock_time=-100
        self.depth_time=-100; self.raise_time=-100; self.radar_hits=0
        self.samples=0; self.raw=''; self.log=None
    def start_cal(self):
        if time.monotonic()-self.st>2: raise ValueError('Connect sensors first.')
        self.cal=[]; self.calibrating=True; self.baseline=None
        self.ranges=[]; self.deep_count=self.raised_count=0
        self.depth_time=self.raise_time=self.shock_time=-100
    def add_event(self, kind, evidence):
        now=time.monotonic()
        if now-self.last_event.get(kind,-100)<self.cfg['event_cooldown_s']: return
        self.last_event[kind]=now
        s=self.sensor
        fix=now-self.st<2 and s.get('gps_fix') is True and finite(s.get('lat')) and finite(s.get('lon')) and abs(s['lat'])<=90 and abs(s['lon'])<=180
        e={'time':utc(),'kind':kind,'lat':s['lat'] if fix else None,'lon':s['lon'] if fix else None,'evidence':evidence,'demo':self.demo}
        if self.store: self.store.put('event',e)
        self.events.insert(0,e); self.events=self.events[:500]
        if self.log:
            self.log.write(json.dumps({'type':'event',**e})+'\n'); self.log.flush()
    def ingest_radar(self,r):
        now=time.monotonic()
        if now-self.rt>1: self.radar_hits=0
        self.radar=r; self.rt=now
        c=self.cfg
        in_roi=[p for p in r['points'] if abs(p['x'])<c['radar_half_width_m'] and c['radar_near_m']<p['y']<c['radar_far_m'] and c.get('radar_z_min_m',-2)<p['z']<c.get('radar_z_max_m',2)]
        self.radar_hits=self.radar_hits+1 if r['supported'] and in_roi else 0
    def ingest(self,s):
        if not isinstance(s,dict) or not all(k in s for k in ('distance_mm','az_mv','gps_fix')): return False
        for key in ('distance_mm','ax_mv','ay_mv','az_mv','lat','lon','speed_kmph','satellites'):
            if s.get(key) is not None and not finite(s[key]): return False
        now=time.monotonic()
        if now-self.st>2:
            self.depth_time=self.raise_time=self.shock_time=-100
            self.ranges=[]; self.deep_count=self.raised_count=0
        self.sensor=s; self.st=now; self.samples+=1; self.errors.pop('sensors',None)
        valid=s.get('tof_ok') is True and s.get('range_status')==0 and finite(s.get('distance_mm')) and 0<s['distance_mm']<8000
        axis=self.cfg['vertical_axis']+'_mv'; a=s.get(axis)
        if self.calibrating and valid and finite(a):
            self.cal.append((s['distance_mm'],a))
            if len(self.cal)>=30:
                ds,aa=zip(*self.cal)
                if max(ds)-min(ds)>30 or max(aa)-min(aa)>35:
                    self.errors['calibration']='Too much movement; keep stationary and calibrate again.'
                else:
                    self.baseline={'distance_mm':sum(ds)/len(ds),'axis_mv':sum(aa)/len(aa)}
                    self.errors.pop('calibration',None)
                self.calibrating=False
        delta=None; shock=None
        if self.baseline and finite(a):
            shock=abs(a-self.baseline['axis_mv'])/self.cfg['accel_mv_per_g']
            if shock>self.cfg['shock_g']: self.shock_time=now
            if valid:
                self.ranges.append(s['distance_mm']); self.ranges=self.ranges[-3:]
                delta=median(self.ranges)-self.baseline['distance_mm']
                self.deep_count=self.deep_count+1 if delta>self.cfg['depth_mm'] else 0
                self.raised_count=self.raised_count+1 if delta < -self.cfg['raised_mm'] else 0
                if self.deep_count>=self.cfg.get('persistence_samples',2): self.depth_time=now
                if self.raised_count>=self.cfg.get('persistence_samples',2): self.raise_time=now
            else:
                self.ranges=[]; self.deep_count=self.raised_count=0
                self.depth_time=self.raise_time=-100
            if now-self.depth_time<0.8 and now-self.shock_time<0.8:
                self.add_event('Possible pothole',f'Distance increase > {self.cfg["depth_mm"]} mm + vertical transient')
            if now-self.raise_time<0.8:
                if now-self.rt<1 and self.radar.get('supported') and self.radar_hits>=3:
                    self.add_event('Possible raised object / debris','Reduced ground clearance + radar returns in forward region')
                elif now-self.shock_time<0.8:
                    self.add_event('Possible bump','Reduced ground clearance + vertical transient')
        self.cleaned={'clearance_delta_mm':delta,'vertical_transient_g':shock,'range_valid':valid,'radar_persistent_hits':self.radar_hits}
        if self.store and now-self.last_snapshot>=self.cfg.get('cloud_snapshot_s',30):
            self.store.put('sample',{'time':utc(),'sensor':s,'cleaned':self.cleaned,'radar':dict(self.radar,points=self.radar.get('points',[])[:256],point_count=len(self.radar.get('points',[]))) if now-self.rt<2 else None,'baseline':self.baseline,'demo':self.demo})
            self.last_snapshot=now
        self.trace.append({'delta':delta,'shock':shock}); self.trace=self.trace[-160:]
        if self.log:
            self.log.write(json.dumps({'type':'sample','time':utc(),'sensor':s,'radar_frame':self.radar.get('frame')})+'\n')
            if self.samples%10==0:self.log.flush()
        return True
    def state(self):
        now=time.monotonic()
        return {'mode':'DEMO — simulated data' if self.demo else 'LIVE — hardware input',
                'sensor':self.sensor,'radar':self.radar,'sensor_online':now-self.st<2,
                'radar_online':now-self.rt<2,'errors':self.errors,'baseline':self.baseline,
                'calibrating':self.calibrating,'cal_samples':len(self.cal),'trace':self.trace,
                'events':self.events,'samples':self.samples,'raw':self.raw,
                'cleaned':self.cleaned,'transport':self.transport,'storage':self.store.status() if self.store else {},
                'config':self.cfg,'ice':'Not assessed — no validated ice model or surface-temperature input'}

def sensor_loop(m,port,baud):
    import serial
    while True:
        try:
            with serial.Serial(port,baud,timeout=1) as ser:
                while True:
                    raw=ser.read_until(b'\n',4096).decode(errors='replace').strip()
                    if not raw: continue
                    with LOCK:
                        m.raw=raw[:500]
                        try:
                            if not m.ingest(json.loads(raw)): m.errors['sensors']='Unexpected JSON fields; use included ESP32 firmware.'
                        except (ValueError,TypeError): m.errors['sensors']='Non-JSON packet; check firmware and baud rate.'
        except Exception as e:
            with LOCK:m.errors['sensors']=str(e)
            time.sleep(2)

def radar_loop(m,port,baud,cli,cfg):
    import serial
    while True:
        try:
            with serial.Serial(port,baud,timeout=.2) as ser:
                if cfg:
                    with serial.Serial(cli,115200,timeout=.2) as command:
                        time.sleep(.5); command.reset_input_buffer()
                        for line in Path(cfg).read_text().splitlines():
                            line=line.strip()
                            if not line or line.startswith(('%','#')): continue
                            command.write((line+'\n').encode()); command.flush()
                            deadline=time.monotonic()+3; reply=b''
                            while time.monotonic()<deadline:
                                reply+=command.read(command.in_waiting or 1)
                                if b'Done' in reply or b'Error' in reply or b'not recognized' in reply:break
                            if b'Done' not in reply:
                                raise ValueError('Radar config failed at '+line+': '+reply.decode(errors='replace'))
                    cfg=None
                p=RadarParser()
                while True:
                    data=ser.read(ser.in_waiting or 1)
                    for r in p.feed(data):
                        with LOCK:
                            m.ingest_radar(r)
                            if r['supported']:m.errors.pop('radar',None)
                            else:m.errors['radar']='Unsupported point TLV. Requires SDK 3.x out-of-box firmware.'
        except Exception as e:
            with LOCK:m.errors['radar']=str(e)
            time.sleep(2)

def demo_loop(m):
    i=0
    while True:
        phase=i%180; dip=100 if 60<=phase<64 else -85 if 120<=phase<124 else 0
        s={'tof_ok':True,'range_status':0,'distance_mm':450+dip+random.uniform(-3,3),
           'ax_mv':1650,'ay_mv':1650,'az_mv':1980+(220 if dip else random.uniform(-4,4)),
           'gps_fix':True,'lat':32.985+math.sin(i/300)*.001,'lon':-96.75+i*.000002,
           'speed_kmph':12.5,'satellites':9}
        r={'frame':i,'supported':True,'types':[1], 'points':[{'x':.25,'y':1.5,'z':-.15,'v':0}] if phase>110 else []}
        with LOCK:
            m.ingest_radar(r); m.ingest(s)
        i+=1; time.sleep(.1)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def reply(self,data,typ='application/json',status=200):
        if not isinstance(data,bytes):data=data.encode()
        self.send_response(status);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/api/state':
            with LOCK:self.reply(json.dumps(M.state(),allow_nan=False))
        elif self.path=='/api/events.csv':
            out=io.StringIO(); fields=['time','kind','lat','lon','evidence','demo'];w=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');w.writeheader()
            with LOCK:w.writerows(M.store.events() if M.store else M.events)
            self.reply(out.getvalue(),'text/csv')
        elif self.path in ('/','/index.html'):self.reply((ROOT/'static/index.html').read_bytes(),'text/html; charset=utf-8')
        else:self.reply('Not found','text/plain',404)
    def do_POST(self):
        if self.path!='/api/calibrate':return self.reply('{}',status=404)
        # Same-origin requests only; local app has no cross-origin API.
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+self.headers.get('Host',''):return self.reply('{}',status=403)
        try:
            with LOCK:M.start_cal()
            self.reply('{"ok":true}')
        except ValueError as e:self.reply(json.dumps({'error':str(e)}),status=400)

def main():
    global M
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--demo',action='store_true');p.add_argument('--list-ports',action='store_true')
    p.add_argument('--ble-address',help='ESP32 BLE address, or auto for named discovery');p.add_argument('--cloud',action='store_true',help='Enable Firebase Firestore upload');
    p.add_argument('--sensor-port');p.add_argument('--sensor-baud',type=int,default=115200)
    p.add_argument('--radar-data-port');p.add_argument('--radar-cli-port');p.add_argument('--radar-config')
    p.add_argument('--radar-baud',type=int,default=921600);p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8000)
    a=p.parse_args()
    if a.list_ports:
        from serial.tools import list_ports
        for s in list_ports.comports():print(s.device,'|',s.description,'|',s.hwid)
        return
    if not a.demo and not (a.sensor_port or a.ble_address or a.radar_data_port):p.error('Use --demo or supply hardware serial ports.')
    if a.sensor_port and a.ble_address:p.error('Select USB sensor input OR BLE, not both.')
    if a.cloud and a.demo:p.error('Demo data stays local; remove --cloud.')
    if a.radar_config and not (a.radar_cli_port and a.radar_data_port):p.error('Config needs both radar ports.')
    ports=[x for x in (a.sensor_port,a.radar_data_port,a.radar_cli_port) if x]
    if len(set(ports))!=len(ports):p.error('Each device/role needs a different port.')
    cfg=json.loads((ROOT/'config.json').read_text())
    if cfg['vertical_axis'] not in ('ax','ay','az') or cfg['accel_mv_per_g']<=0: p.error('Invalid calibration config')
    folder=ROOT/'logs';folder.mkdir(exist_ok=True)
    store=Store(folder/('demo.sqlite3' if a.demo else 'live.sqlite3'))
    M=Monitor(cfg,a.demo,store)
    M.transport='BLE' if a.ble_address else 'USB'
    if a.cloud:threading.Thread(target=cloud_loop,args=(store,cfg),daemon=True).start()
    folder=ROOT/'logs';folder.mkdir(exist_ok=True)
    M.log=(folder/(('demo_' if a.demo else 'live_')+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.jsonl')).open('a',buffering=1)
    if a.demo:threading.Thread(target=demo_loop,args=(M,),daemon=True).start()
    else:
        if a.ble_address:threading.Thread(target=ble_loop,args=(M,a.ble_address,LOCK),daemon=True).start()
        if a.sensor_port:threading.Thread(target=sensor_loop,args=(M,a.sensor_port,a.sensor_baud),daemon=True).start()
        if a.radar_data_port:threading.Thread(target=radar_loop,args=(M,a.radar_data_port,a.radar_baud,a.radar_cli_port,a.radar_config),daemon=True).start()
    print(f'Open http://localhost:{a.port}  |  Ctrl+C to stop',flush=True)
    try:ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()
    except KeyboardInterrupt:pass
    finally:M.log.close()
if __name__=='__main__': main()
