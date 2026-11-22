#!/usr/bin/env python3
import argparse, asyncio, csv, io, json, math, os, pathlib, threading, time
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from core import Monitor, Store, SERVICE, TELEMETRY, CONTROL
from radar import Parser, configure
ROOT=pathlib.Path(__file__).resolve().parent

def sensors(m,port):
    import serial
    while True:
        try:
            with serial.Serial(port,115200,timeout=1) as s:
                while True:
                    line=s.readline(4096)
                    if not line: continue
                    try: m.ingest(json.loads(line))
                    except (ValueError,TypeError,AttributeError) as e:
                        with m.lock: m.errors['sensor']=str(e)[:120]
        except Exception as e:
            with m.lock: m.errors['sensor']=type(e).__name__+': check port, permissions and cable'
            time.sleep(3)

def radar(m,port,baud):
    import serial
    while True:
        try:
            parser=Parser()
            with serial.Serial(port,baud,timeout=.2) as s:
                while True:
                    for f in parser.feed(s.read(8192)): m.set_radar(f)
                    if parser.rejected:
                        with m.lock: m.errors['radar']='Rejected UART frames; check SDK3 OOB firmware/config. Count: '+str(parser.rejected)
        except Exception as e:
            with m.lock: m.errors['radar']=type(e).__name__+': check radar data port and firmware'
            time.sleep(3)

def demo(m):
    i=0
    while True:
        phase=i%260; t=i/1000
        mm=580+(85 if 80<phase<90 else -75 if 160<phase<170 else 0)
        m.set_radar({'frame':i,'points':[(0,1,-.5)]*3,'range_power_mean':None})
        m.ingest({'schema':'road-v1','tof_mm':mm,'ax':0,'ay':0,'az':1+.02*math.sin(i),
                  'gps_fix':True,'lat':32.985+0.001*math.sin(t),'lon':-96.75+0.001*math.cos(t),
                  'speed_kmh':8,'satellites':9})
        i+=1; time.sleep(.1)

def cloud(m,key):
    # Explicit credentials on Pi only. Idempotent document IDs survive retries/reboots.
    import firebase_admin
    from firebase_admin import credentials, firestore
    with m.lock: m.cloud['enabled']=True
    db=None
    while True:
        try:
            if db is None:
                app=firebase_admin.get_app() if firebase_admin._apps else firebase_admin.initialize_app(credentials.Certificate(key))
                db=firestore.client(app)
            rows=m.store.pending()
            if rows:
                batch=db.batch()
                for ident,session,ts,kind,payload in rows:
                    ref=db.collection(m.c['cloud_collection']).document(m.c['cloud_device_id']).collection('records').document(ident)
                    batch.set(ref,{'session':session,'timestamp':ts,'kind':kind,'data':json.loads(payload)})
                batch.commit(timeout=15)
                m.store.mark([r[0] for r in rows])
                with m.lock: m.cloud.update(last_sync=time.time(),error=None)
            time.sleep(2)
        except Exception as e:
            # Never echo credentials or full provider payloads into BLE/browser logs.
            msg='Cloud unavailable ('+type(e).__name__+'). Data remains queued on Pi.'
            if 'Invalid JWT Signature' in str(e): msg='Firebase key rejected: generate a new service-account key and restart.'
            with m.lock: m.cloud['error']=msg
            time.sleep(10)

async def ble(m,token):
    from bless import BlessServer, GATTCharacteristicProperties as P, GATTAttributePermissions as A
    server=BlessServer(name='RoadMonitor-Pi',loop=asyncio.get_running_loop())
    def write(characteristic,value,**kwargs):
        try:
            # ASCII: six-digit local control code + ':' + verb, <=20 bytes.
            code,cmd=bytes(value).decode().split(':',1)
            if code!=token: return
            m.command(cmd)
        except (ValueError,UnicodeError): pass
    server.write_request_func=write
    await server.add_new_service(SERVICE)
    await server.add_new_characteristic(SERVICE,TELEMETRY,P.notify,bytearray(),A.readable)
    await server.add_new_characteristic(SERVICE,CONTROL,P.write,bytearray(),A.writable)
    await server.start()
    print('BLE advertising: RoadMonitor-Pi. Browser controls require your --control-code.')
    try:
        while True:
            # 20-byte notifications work with default ATT MTU; RS starts a frame and LF ends it.
            data=b'\x1e'+json.dumps(m.snapshot(),separators=(',',':'),ensure_ascii=True).encode()+b'\n'
            for offset in range(0,len(data),20):
                server.get_characteristic(TELEMETRY).value=bytearray(data[offset:offset+20])
                server.update_value(SERVICE,TELEMETRY)
                await asyncio.sleep(.015)
            await asyncio.sleep(.1)
    finally: await server.stop()

def http(m,port,token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a): pass
        def reply(self,code,data,kind='application/json'):
            self.send_response(code); self.send_header('Content-Type',kind); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            route=urlsplit(self.path)
            if route.path in ('/api/sessions','/api/history','/api/export'):
                if self.headers.get('X-Control-Code')!=token:
                    return self.reply(403,b'{"error":"Wrong control code"}')
                if route.path=='/api/sessions':
                    return self.reply(200,json.dumps(m.store.sessions()).encode())
                session=parse_qs(route.query).get('session',[''])[0]
                if len(session)!=32 or any(c not in '0123456789abcdef' for c in session):
                    return self.reply(400,b'{"error":"Invalid session"}')
                if route.path=='/api/history':
                    return self.reply(200,json.dumps(m.store.history(session)).encode())
                out=io.StringIO(); writer=csv.writer(out)
                writer.writerow(['timestamp','session','kind','payload_json','synced'])
                writer.writerows(m.store.csv_rows(session))
                return self.reply(200,out.getvalue().encode(),'text/csv; charset=utf-8')
            if self.path=='/api/state': self.reply(200,json.dumps(m.snapshot()).encode())
            elif self.path in ('/','/index.html'): self.reply(200,(ROOT/'web/index.html').read_bytes(),'text/html; charset=utf-8')
            else: self.reply(404,b'{}')
        def do_POST(self):
            if self.path!='/api/command': return self.reply(404,b'{}')
            if self.headers.get('X-Control-Code')!=token: return self.reply(403,b'{"error":"Wrong control code"}')
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n<1 or n>100: raise ValueError()
                m.command(json.loads(self.rfile.read(n))['command']); self.reply(200,b'{}')
            except Exception: self.reply(400,b'{"error":"Invalid command"}')
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()

def main():
    p=argparse.ArgumentParser(description='RoadMonitor: USB sensors/radar -> Pi -> BLE browser')
    p.add_argument('--sensor-port'); p.add_argument('--radar-data-port'); p.add_argument('--radar-cli-port'); p.add_argument('--radar-config')
    p.add_argument('--radar-baud',type=int,default=921600); p.add_argument('--config',default=str(ROOT/'config.json'))
    p.add_argument('--db',default=str(ROOT/'recordings.sqlite')); p.add_argument('--cloud-key'); p.add_argument('--ble',action='store_true')
    p.add_argument('--demo',action='store_true'); p.add_argument('--port',type=int,default=8000)
    p.add_argument('--control-code',required=True,help='Choose six digits for local recording/calibration commands')
    a=p.parse_args()
    if len(a.control_code)!=6 or not a.control_code.isdigit(): p.error('--control-code must have six digits')
    if not a.demo and not a.sensor_port: p.error('--sensor-port is required unless --demo')
    if a.demo and a.cloud_key: p.error('Demo cloud upload disabled: keep synthetic data out of live project')
    if a.radar_config and not (a.radar_cli_port and a.radar_data_port): p.error('Radar config requires both CLI and data ports')
    c=json.load(open(a.config))
    if c['cloud_snapshot_s']<=0 or c['persistence_samples']<1: p.error('Invalid recording / detection settings')
    if a.cloud_key:
        if not os.path.isfile(a.cloud_key): p.error('Firebase key file not found')
        import firebase_admin  # fail visibly at startup if optional dependency missing
    m=Monitor(c,Store(a.db),a.demo)
    def start(fn,*args): threading.Thread(target=fn,args=args,daemon=True).start()
    # Open data reader before sensorStart to avoid dropping initial frames.
    if a.radar_data_port:start(radar,m,a.radar_data_port,a.radar_baud)
    if a.radar_config: configure(a.radar_cli_port,a.radar_config)
    start(demo,m) if a.demo else start(sensors,m,a.sensor_port)
    if a.cloud_key:start(cloud,m,a.cloud_key)
    print(f'Pi browser: http://localhost:{a.port}. Press Ctrl+C to stop. Recording starts only with Start recording.')
    if a.ble:
        start(http,m,a.port,a.control_code)
        asyncio.run(ble(m,a.control_code))
    else:http(m,a.port,a.control_code)
if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: pass
