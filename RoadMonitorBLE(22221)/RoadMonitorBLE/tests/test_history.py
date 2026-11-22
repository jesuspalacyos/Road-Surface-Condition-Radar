import json, pathlib, tempfile, unittest
from core import Monitor,Store

class HistoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.store=Store(self.tmp.name+'/db')
  self.c=json.loads((pathlib.Path(__file__).resolve().parents[1]/'config.json').read_text())
 def tearDown(self):
  self.store.db.close();self.tmp.cleanup()
 def test_demo_never_queues(self):
  m=Monitor(self.c,self.store,True);m.command('start')
  m.ingest({'schema':'road-v1','tof_mm':580,'az':1});m.command('stop')
  self.assertEqual(self.store.counts(),(3,0))
 def test_sessions_isolated_and_ordered(self):
  for sid in ('a'*32,'b'*32):
   for i in range(3):self.store.add(sid,'event',{'i':i},True)
  self.assertEqual(len(self.store.sessions()),2)
  self.assertEqual([r['data']['i'] for r in self.store.history('a'*32,2)],[1,2])
  self.assertEqual(len(self.store.csv_rows('b'*32)),3)
  self.assertEqual(self.store.history("' OR 1=1 --"),[])
 def test_stale_alert_is_cleared(self):
  m=Monitor(self.c,self.store);m.candidate='Possible pothole';m.run=5
  self.assertIsNone(m.snapshot()['current_alert'])
if __name__=='__main__':unittest.main()
