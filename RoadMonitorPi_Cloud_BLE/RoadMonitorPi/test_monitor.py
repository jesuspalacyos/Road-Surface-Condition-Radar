import unittest, struct, json, time, tempfile
from pathlib import Path
from radar import RadarParser, MAGIC
from app import Monitor
from ble_input import Assembler
from storage import Store, sync_once
CFG=json.loads(Path(__file__).with_name('config.json').read_text())
S=dict(distance_mm=450,az_mv=1980,gps_fix=False,lat=None,lon=None,tof_ok=True,range_status=0)
class Tests(unittest.TestCase):
 def monitor(self):
  m=Monitor(CFG);m.ingest(S);m.start_cal()
  for _ in range(30):m.ingest(S)
  return m
 def test_fragmented_radar(self):
  payload=struct.pack('<4f',1,2,3,4);tlv=struct.pack('<II',1,16)+payload
  packet=MAGIC+struct.pack('<8I',0x03000000,40+len(tlv),0xa6843,10,0,1,1,0)+tlv
  p=RadarParser();self.assertEqual(p.feed(b'junk'+packet[:23]),[])
  self.assertEqual(p.feed(packet[23:])[0]['points'][0]['y'],2)
 def test_reject_spike_accept_sustained_pothole(self):
  m=self.monitor();m.ingest(dict(S,distance_mm=550,az_mv=2200));m.ingest(S);m.ingest(S)
  self.assertEqual(m.events,[])
  for _ in range(3):m.ingest(dict(S,distance_mm=550,az_mv=2200))
  self.assertEqual(len(m.events),1);self.assertEqual(m.events[0]['kind'],'Possible pothole')
  self.assertIsNone(m.events[0]['lat'])
 def test_invalid_range_and_stale_inputs(self):
  m=self.monitor()
  for _ in range(5):m.ingest(dict(S,distance_mm=None,az_mv=2200))
  self.assertEqual(m.events,[])
  m.st=time.monotonic()-5
  with self.assertRaises(ValueError):m.start_cal()
  self.assertFalse(m.ingest(dict(S,distance_mm=float('nan'))))
 def test_debris_requires_fresh_persistent_radar(self):
  m=self.monitor();r=dict(supported=True,points=[dict(x=0,y=1,z=0,v=0)],frame=1,types=[1])
  for _ in range(3):m.ingest_radar(r)
  for _ in range(3):m.ingest(dict(S,distance_mm=350))
  self.assertIn('debris',m.events[0]['kind'])
  m.rt=time.monotonic()-3;m.ingest_radar(r)
  self.assertEqual(m.radar_hits,1)
 def test_ble_reassembly_and_loss(self):
  raw=json.dumps(S).encode();chunks=[raw[i:i+16] for i in range(0,len(raw),16)]
  frames=[bytes([1,0,i,len(chunks)])+c for i,c in enumerate(chunks)]
  a=Assembler();outputs=[a.feed(f) for f in frames];self.assertEqual(outputs[-1],S)
  a=Assembler();self.assertTrue(all(a.feed(f) is None for f in frames[:1]+frames[2:]))
 def test_durable_outbox_retry(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'db';st=Store(path);ident=st.put('event',{'time':'now','kind':'Possible pothole'})
   st.db.close();st=Store(path);self.assertEqual(len(st.events()),1)
   class DB:
    fail=True
    def collection(self,*a):return self
    def document(self,x):self.ident=x;return self
    def set(self,*a,**kw):
     if self.fail:raise RuntimeError('offline')
   db=DB()
   with self.assertRaises(RuntimeError):sync_once(st,db,CFG)
   self.assertEqual(st.status()['pending'],1)
   db.fail=False;sync_once(st,db,CFG)
   self.assertEqual(db.ident,ident);self.assertEqual(st.status()['pending'],0)
   st.db.close()
if __name__=='__main__':unittest.main()
