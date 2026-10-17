import unittest, struct, json, time
from pathlib import Path
from radar import RadarParser, MAGIC
from app import Monitor
class Tests(unittest.TestCase):
 def test_fragmented_packet(self):
  payload=struct.pack('<4f',1,2,3,4); tlv=struct.pack('<II',1,16)+payload
  packet=MAGIC+struct.pack('<8I',0x03000000,40+len(tlv),0xa6843,10,0,1,1,0)+tlv
  p=RadarParser();self.assertEqual(p.feed(b'junk'+packet[:23]),[])
  r=p.feed(packet[23:]);self.assertTrue(r[0]['supported']);self.assertEqual(r[0]['points'][0]['y'],2)
  bad=MAGIC+struct.pack('<8I',0,48,0,1,0,1,1,0)+struct.pack('<II',1020,0)
  self.assertFalse(p.feed(bad)[0]['supported'])
 def test_events_and_gps(self):
  m=Monitor(json.loads(Path('config.json').read_text()))
  s=dict(distance_mm=450,az_mv=1980,gps_fix=False,lat=None,lon=None,tof_ok=True,range_status=0)
  m.ingest(s);m.start_cal()
  for _ in range(30):m.ingest(s)
  self.assertIsNotNone(m.baseline)
  m.ingest(dict(s,distance_mm=550,az_mv=2200));self.assertEqual(m.events[0]['kind'],'Possible pothole');self.assertIsNone(m.events[0]['lat'])
  m.events=[];m.depth_time=-100;m.shock_time=-100
  m.ingest(dict(s,distance_mm=None,az_mv=2200));self.assertEqual(m.events,[])
  m.st=time.monotonic()-5
  with self.assertRaises(ValueError):m.start_cal()
if __name__=='__main__':unittest.main()
