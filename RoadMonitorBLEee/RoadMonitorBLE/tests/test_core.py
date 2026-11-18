import unittest,tempfile,struct,json,sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from core import Monitor,Store,normalize
from radar import Parser,MAGIC
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sample(**kw):
 d=dict(schema='road-v1',tof_mm=580,ax=0,ay=0,az=1,gps_fix=True,lat=32.9,lon=-96.7,speed_kmh=5,satellites=8);d.update(kw);return d
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name+'/db');self.m=Monitor(json.loads((ROOT/'config.json').read_text()),self.store)
 def tearDown(self):self.store.db.close();self.tmp.cleanup()
 def calibrate(self):
  self.m.command('calibrate')
  for _ in range(30):self.m.ingest(sample())
 def test_invalid_values(self):
  d=normalize(sample(tof_mm=float('nan'),lat=100));self.assertIsNone(d['tof_mm']);self.assertFalse(d['gps_fix']);self.assertIsNone(d['lon'])
  with self.assertRaises(ValueError):normalize({})
 def test_calibration_and_pothole(self):
  self.calibrate();self.assertEqual(self.m.baseline,(580,1));self.m.ingest(sample(tof_mm=650));self.assertFalse(self.m.events)
  self.m.ingest(sample(tof_mm=650));self.assertEqual(self.m.events[0]['label'],'Possible pothole');self.assertFalse(self.m.events[0]['verified'])
 def test_unstable_calibration(self):
  self.m.command('calibrate')
  for i in range(30):self.m.ingest(sample(tof_mm=500+i*4))
  self.assertIsNone(self.m.baseline)
 def test_no_alert_without_calibration(self):
  for _ in range(10):self.m.ingest(sample(tof_mm=900))
  self.assertFalse(self.m.events)
 def test_record_and_queue(self):
  self.m.ingest(sample());self.assertEqual(self.store.counts(),(0,0))
  self.m.command('start');self.m.ingest(sample());self.m.ingest(sample());self.m.command('stop');self.m.ingest(sample())
  self.assertEqual(self.store.counts(),(4,3));rows=self.store.pending();self.store.mark([rows[0][0]]);self.assertEqual(self.store.counts(),(4,2))
  self.store.db.close();self.store=Store(self.tmp.name+'/db');self.assertEqual(self.store.counts(),(4,2))
 def test_stale_data(self):
  self.m.ingest(sample());self.m.sensor_at-=10;self.assertFalse(self.m.snapshot()['sensor_fresh'])
 def test_radar_evidence_requires_geometry(self):
  f={'points':[(0,1,-.6)]*3,'frame':3};self.m.set_radar(f);self.assertIsNone(self.m.radar['height_mm'])
  self.m.c.update(radar_mount_height_m=.5,radar_pitch_down_deg=0);self.m.set_radar(f);self.assertAlmostEqual(self.m.radar['height_mm'],-100)
 def test_parser_split_and_resync(self):
  body=struct.pack('<ffff',.1,1,-.5,0);tlv=struct.pack('<II',1,len(body))+body
  packet=MAGIC+struct.pack('<8I',0x03050000,40+len(tlv),0x6843,10,0,1,1,0)+tlv
  p=Parser();self.assertEqual(p.feed(b'garbage'+packet[:25]),[]);f=p.feed(packet[25:]);self.assertEqual(f[0]['frame'],10);self.assertEqual(len(f[0]['points']),1)
  bad=MAGIC+struct.pack('<8I',0,42,0,0,0,1,1,0)+b'xx';self.assertEqual(p.feed(bad),[]);self.assertEqual(p.rejected,1);self.assertEqual(len(p.feed(packet)),1)
 def test_no_gps_zero_fabrication(self):
  self.m.ingest(sample(gps_fix=False));self.assertIsNone(self.m.sensor['lat'])
if __name__=='__main__':unittest.main()
