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
 def test_side_info_snr(self):
  pts=struct.pack('<4f',0,2,0,0)+struct.pack('<4f',0,3,0,0)
  t1=struct.pack('<II',1,len(pts))+pts; t7=struct.pack('<II',7,8)+struct.pack('<hhhh',150,20,55,20)
  pkt=MAGIC+struct.pack('<8I',0x03060000,40+len(t1)+len(t7),0xa6843,1,0,2,2,0)+t1+t7
  r=RadarParser().feed(pkt)[0]
  self.assertEqual([q['snr'] for q in r['points']],[15.0,5.5])
 def test_tilt_and_radar_events(self):
  cfg=dict(json.loads(Path('config.json').read_text()),radar_height_m=1.0,radar_pitch_deg=30.0)
  m=Monitor(cfg)
  # A flat-road point 2 m ahead along the road, seen by a radar 1 m up tilted 30 deg down.
  import math
  t=math.radians(30); fwd,up=2.0,-1.0
  y=fwd*math.cos(t)-up*math.sin(t); z=fwd*math.sin(t)+up*math.cos(t)
  q=m.to_road({'x':0,'y':y,'z':z,'v':0,'snr':None})
  self.assertAlmostEqual(q['forward'],2.0,places=6); self.assertAlmostEqual(q['height'],0.0,places=6)
  # Three frames with 3 points 20 cm above the road -> one radar debris event.
  def frame(k,h):
   pts=[]
   for dx in (-0.1,0,0.1):
    up=h-1.0; y=fwd*math.cos(t)-up*math.sin(t); z=fwd*math.sin(t)+up*math.cos(t)
    pts.append({'x':dx,'y':y,'z':z,'v':0,'snr':20.0})
   return {'frame':k,'points':pts,'types':[1,7],'supported':True}
  for k in range(3): m.ingest_radar(frame(k,0.20))
  self.assertEqual(m.events[0]['kind'],'Radar: possible raised object / debris')
  self.assertEqual(m.radar_analysis['debris'],3)
  # Flat road points produce no new event and reset the counter.
  m.ingest_radar(frame(4,0.0)); self.assertEqual(m.debris_frames,0); self.assertEqual(len(m.events),1)
 def test_peak_accel_used(self):
  m=Monitor(json.loads(Path('config.json').read_text()))
  s=dict(distance_mm=450,az_mv=1980,az_min_mv=1975,az_max_mv=1985,gps_fix=False,lat=None,lon=None,tof_ok=True,range_status=0)
  m.ingest(s);m.start_cal()
  for _ in range(30):m.ingest(s)
  # Mean barely moves but the window max spikes by 0.6 g -> shock detected.
  m.ingest(dict(s,az_mv=1985,az_max_mv=1980+int(0.6*330)))
  self.assertGreater(m.trace[-1]['shock'],0.5)
if __name__=='__main__':unittest.main()
