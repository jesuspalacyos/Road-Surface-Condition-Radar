#!/usr/bin/env python3
"""Local Raspberry Pi road-monitor prototype. No trained road classifier."""
import argparse, csv, glob, io, json, math, random, threading, time
from pathlib import Path
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from radar import RadarParser
ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock()
# Defaults for settings added during team integration; config.json overrides them.
DEFAULTS={
    'radar_height_m':0.60,      # radar height above the road (m) - MEASURE YOURS
    'radar_pitch_deg':0.0,      # radar down-tilt (deg, positive = pointing at road) - MEASURE YOURS
    'radar_snr_min_db':8.0,     # ignore weaker radar points
    'debris_min_m':0.08,        # point this far above road = raised object candidate
    'debris_max_m':0.80,
    'depression_m':-0.07,       # point this far below road = depression candidate
    'radar_min_points':3,       # points needed in one frame
    'radar_frames_required':3,  # consecutive frames needed before an event
    'radar_reconfig_s':5.0,     # no frames this long -> reopen port and re-send config
    'radar_log_every':1,        # log every Nth radar frame (1 = all)
}
def finite(v): return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def utc(): return datetime.now(timezone.utc).isoformat()
class Monitor:
    def __init__(self, cfg, demo=False):
        self.cfg={**DEFAULTS,**cfg}; self.demo=demo; self.sensor={}; self.radar={}; self.st=0; self.rt=0
        self.errors={}; self.baseline=None; self.cal=[]; self.calibrating=False
        self.events=[]; self.trace=[]; self.last_event={}; self.shock_time=-100
        self.depth_time=-100; self.raise_time=-100; self.radar_hits=0
        self.samples=0; self.raw=''; self.log=None
        self.radar_analysis=None; self.debris_frames=0; self.dip_frames=0; self.radar_frames=0
    def start_cal(self):
        if time.monotonic()-self.st>2: raise ValueError('Connect sensors first.')
        self.cal=[]; self.calibrating=True; self.baseline=None
        self.depth_time=self.raise_time=self.shock_time=-100
    def add_event(self, kind, evidence):
        now=time.monotonic()
        if now-self.last_event.get(kind,-100)<self.cfg['event_cooldown_s']: return
        self.last_event[kind]=now
        s=self.sensor
        fix=now-self.st<2 and s.get('gps_fix') is True and finite(s.get('lat')) and finite(s.get('lon')) and abs(s['lat'])<=90 and abs(s['lon'])<=180
        e={'time':utc(),'kind':kind,'lat':s['lat'] if fix else None,'lon':s['lon'] if fix else None,'evidence':evidence,'demo':self.demo}
        self.events.insert(0,e); self.events=self.events[:500]
        if self.log:
            self.log.write(json.dumps({'type':'event',**e})+'\n'); self.log.flush()
    def to_road(self,p):
        """Radar coordinates -> road coordinates using mount height and down-tilt."""
        c=self.cfg; t=math.radians(c['radar_pitch_deg'])
        fwd=p['y']*math.cos(t)+p['z']*math.sin(t)
        up=-p['y']*math.sin(t)+p['z']*math.cos(t)
        return {**p,'forward':fwd,'lateral':p['x'],'height':up+c['radar_height_m']}
    def ingest_radar(self,r):
        self.rt=time.monotonic(); c=self.cfg
        if r['supported']:
            r={**r,'points':[self.to_road(p) for p in r['points']]}
        self.radar=r; self.radar_frames+=1
        if not r['supported']:
            self.radar_hits=self.debris_frames=self.dip_frames=0; self.radar_analysis=None; return
        lane=[p for p in r['points'] if abs(p['lateral'])<c['radar_half_width_m']
              and c['radar_near_m']<p['forward']<c['radar_far_m']
              and (p.get('snr') is None or p['snr']>=c['radar_snr_min_db'])]
        debris=[p for p in lane if c['debris_min_m']<=p['height']<=c['debris_max_m']]
        dips=[p for p in lane if p['height']<=c['depression_m']]
        surface=[p['height'] for p in lane if abs(p['height'])<=0.25]
        rough=None
        if len(surface)>=4:
            m=sum(surface)/len(surface); rough=math.sqrt(sum((h-m)**2 for h in surface)/len(surface))
        self.debris_frames=self.debris_frames+1 if len(debris)>=c['radar_min_points'] else 0
        self.dip_frames=self.dip_frames+1 if len(dips)>=c['radar_min_points'] else 0
        # radar_hits feeds the ToF+radar fusion rule: consecutive frames with raised points in the lane.
        self.radar_hits=self.debris_frames
        self.radar_analysis={'lane':len(lane),'debris':len(debris),'depressions':len(dips),'roughness_m':rough}
        need=c['radar_frames_required']
        if self.debris_frames==need:
            near=min(debris,key=lambda p:p['forward'])
            self.add_event('Radar: possible raised object / debris',
                f'{len(debris)} pts {c["debris_min_m"]*100:.0f}-{c["debris_max_m"]*100:.0f} cm above road for {need} frames, nearest {near["forward"]:.1f} m ahead')
        if self.dip_frames==need:
            near=min(dips,key=lambda p:p['forward'])
            self.add_event('Radar: possible depression',
                f'{len(dips)} pts > {abs(c["depression_m"])*100:.0f} cm below road for {need} frames, nearest {near["forward"]:.1f} m ahead')
        if self.log and self.radar_frames%max(1,int(c['radar_log_every']))==0:
            pts=[{k:(round(v,4) if isinstance(v,float) else v) for k,v in p.items()} for p in r['points']]
            self.log.write(json.dumps({'type':'radar','time':utc(),'frame':r['frame'],'points':pts,'analysis':self.radar_analysis})+'\n')
            if self.radar_frames%10==0: self.log.flush()
    def ingest(self,s):
        if not isinstance(s,dict) or not all(k in s for k in ('distance_mm','az_mv','gps_fix')): return False
        for key in ('distance_mm','ax_mv','ay_mv','az_mv','ax_min_mv','ax_max_mv','ay_min_mv','ay_max_mv','az_min_mv','az_max_mv','lat','lon','speed_kmph','satellites'):
            if s.get(key) is not None and not finite(s[key]): return False
        now=time.monotonic()
        if now-self.st>2: self.depth_time=self.raise_time=self.shock_time=-100
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
            base=self.baseline['axis_mv']; lo=s.get(self.cfg['vertical_axis']+'_min_mv'); hi=s.get(self.cfg['vertical_axis']+'_max_mv')
            # Firmware v2 sends the min/max of ~100 samples per report, so short jolts are not averaged away.
            dev=max(abs(hi-base),abs(lo-base)) if finite(lo) and finite(hi) else abs(a-base)
            shock=dev/self.cfg['accel_mv_per_g']
            if shock>self.cfg['shock_g']: self.shock_time=now
            if valid:
                delta=s['distance_mm']-self.baseline['distance_mm']
                if delta>self.cfg['depth_mm']: self.depth_time=now
                if delta < -self.cfg['raised_mm']: self.raise_time=now
            if now-self.depth_time<0.8 and now-self.shock_time<0.8:
                self.add_event('Possible pothole',f'Distance increase > {self.cfg["depth_mm"]} mm + vertical transient')
            if now-self.raise_time<0.8:
                if now-self.rt<1 and self.radar.get('supported') and self.radar_hits>=3:
                    self.add_event('Possible raised object / debris','Reduced ground clearance + radar returns in forward region')
                elif now-self.shock_time<0.8:
                    self.add_event('Possible bump','Reduced ground clearance + vertical transient')
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
                'config':self.cfg,'radar_analysis':self.radar_analysis,
                'mount':{'height_m':self.cfg['radar_height_m'],'pitch_deg':self.cfg['radar_pitch_deg']},'ice':'Not assessed — no validated ice model or surface-temperature input'}

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
                p=RadarParser(); last=time.monotonic()
                while True:
                    data=ser.read(ser.in_waiting or 1)
                    frames=p.feed(data)
                    if frames: last=time.monotonic()
                    elif time.monotonic()-last>m.cfg['radar_reconfig_s']:
                        # Radar reset / unplugged / stopped: reopen and (if we have a cfg) reconfigure.
                        raise RuntimeError(f"No radar frames for {m.cfg['radar_reconfig_s']:.0f} s - reopening"+(' and re-sending config' if cfg else ''))
                    for r in frames:
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

def find_ports():
    """Find devices by stable /dev/serial/by-id names (Linux / Raspberry Pi)."""
    ids=sorted(glob.glob('/dev/serial/by-id/*'))
    found={}
    cp=[p for p in ids if 'CP2105' in p]                      # standalone ISK: if00=CLI, if01=DATA
    xds=[p for p in ids if 'XDS110' in p]                     # ISK on mmWaveICBoost: if00=CLI, if03=DATA
    for group,cli_tag,data_tag in ((cp,'-if00','-if01'),(xds,'-if00','-if03')):
        cli=[p for p in group if cli_tag in p]; data=[p for p in group if data_tag in p]
        if cli and data: found['radar_cli']=cli[0]; found['radar_data']=data[0]; break
    esp=[p for p in ids if any(k in p for k in ('Espressif','ESP32','esp32','XIAO'))]
    if not esp:
        taken=set(found.values())
        esp=[p for p in sorted(glob.glob('/dev/ttyACM*')) if p not in taken]
    if esp: found['sensor']=esp[0]
    return found

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
            out=io.StringIO(); fields=['time','kind','lat','lon','evidence','demo'];w=csv.DictWriter(out,fieldnames=fields);w.writeheader()
            with LOCK:w.writerows(M.events)
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
    p.add_argument('--sensor-port');p.add_argument('--sensor-baud',type=int,default=115200)
    p.add_argument('--radar-data-port');p.add_argument('--radar-cli-port');p.add_argument('--radar-config')
    p.add_argument('--auto',action='store_true',help='Find ESP32 + radar ports automatically and use profile.cfg next to app.py')
    p.add_argument('--radar-baud',type=int,default=921600);p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8000)
    a=p.parse_args()
    if a.list_ports:
        from serial.tools import list_ports
        for s in list_ports.comports():print(s.device,'|',s.description,'|',s.hwid)
        return
    if not a.demo and (a.auto or not (a.sensor_port or a.radar_data_port)):
        f=find_ports()
        a.sensor_port=a.sensor_port or f.get('sensor')
        a.radar_data_port=a.radar_data_port or f.get('radar_data')
        a.radar_cli_port=a.radar_cli_port or f.get('radar_cli')
        default_cfg=ROOT/'profile.cfg'
        if a.radar_cli_port and a.radar_data_port and not a.radar_config and default_cfg.exists(): a.radar_config=str(default_cfg)
        print('Auto ports -> sensors:',a.sensor_port,'| radar CLI:',a.radar_cli_port,'| radar DATA:',a.radar_data_port,'| config:',a.radar_config,flush=True)
    if not a.demo and not (a.sensor_port or a.radar_data_port):p.error('No devices found. Use --demo, or pass --sensor-port / --radar-data-port.')
    if a.radar_config and not (a.radar_cli_port and a.radar_data_port):p.error('Config needs both radar ports.')
    ports=[x for x in (a.sensor_port,a.radar_data_port,a.radar_cli_port) if x]
    if len(set(ports))!=len(ports):p.error('Each device/role needs a different port.')
    cfg={**DEFAULTS,**json.loads((ROOT/'config.json').read_text())}
    if cfg['vertical_axis'] not in ('ax','ay','az') or cfg['accel_mv_per_g']<=0: p.error('Invalid calibration config')
    M=Monitor(cfg,a.demo)
    folder=ROOT/'logs';folder.mkdir(exist_ok=True)
    M.log=(folder/(('demo_' if a.demo else 'live_')+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.jsonl')).open('a',buffering=1)
    if a.demo:threading.Thread(target=demo_loop,args=(M,),daemon=True).start()
    else:
        if a.sensor_port:threading.Thread(target=sensor_loop,args=(M,a.sensor_port,a.sensor_baud),daemon=True).start()
        if a.radar_data_port:threading.Thread(target=radar_loop,args=(M,a.radar_data_port,a.radar_baud,a.radar_cli_port,a.radar_config),daemon=True).start()
    print(f'Open http://localhost:{a.port}  |  Ctrl+C to stop',flush=True)
    try:ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()
    except KeyboardInterrupt:pass
    finally:M.log.close()
if __name__=='__main__': main()
