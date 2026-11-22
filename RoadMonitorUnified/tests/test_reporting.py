import csv
import io
import json
import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from core import Monitor, Store
from reporting import iter_csv, report_row, HEADERS

class ReportingTests(unittest.TestCase):
    def setUp(self): self.store=Store(':memory:')
    def tearDown(self): self.store.db.close()
    def test_csv_values_sessions_and_units(self):
        self.store.add('trip-a','sample',{'sensor':{'gps_fix':True,'lat':32.12345678,'lon':-96.7,'tof_mm':650,'depth_mm':70},'assessed':True,'current_alert':'Possible pothole','surface':{'label':'ice','distances':[2,1,.2],'margin':.5}},True)
        self.store.add('trip-b','sample',{'sensor':{}},False)
        data=''.join(iter_csv(self.store,'trip-a'))
        self.assertTrue(data.startswith('\ufeff'))
        rows=list(csv.DictReader(io.StringIO(data.lstrip('\ufeff'))))
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row['Pothole candidate'],'Yes')
        self.assertEqual(row['Debris / raised object candidate'],'No')
        self.assertEqual(row['Surface match (experimental)'],'ice')
        self.assertEqual(row['Verified hazard'],'No')
        self.assertEqual(row['Road drop (mm)'],'70')
        self.assertEqual(row['Latitude (deg)'],'32.123457')
        self.assertEqual(row['Cloud status'],'Queued')
    def test_missing_values_not_negative_detections(self):
        self.store.add('x','sample',{'sensor':{'gps_fix':False,'lat':1,'lon':2}},False)
        rows=list(csv.reader(io.StringIO(''.join(iter_csv(self.store)).lstrip('\ufeff'))))
        row=dict(zip(HEADERS,rows[1]))
        self.assertEqual(row['Pothole candidate'],'')
        self.assertEqual(row['Latitude (deg)'],'')
        self.assertEqual(row['Cloud status'],'Local only')
    def test_formula_quoting_and_surface_fields(self):
        self.store.add('x','surface',{'label':'ice','distances':[3,2,.1],'margin':.8,'demo':True,'evidence':'=HYPERLINK("x")'},True)
        raw=self.store.pending()[0]
        self.store.mark([raw[0]])
        row=dict(zip(HEADERS,list(csv.reader(io.StringIO(''.join(iter_csv(self.store)).lstrip('\ufeff'))))[1]))
        self.assertEqual(row['Ice match distance'],'0.1')
        self.assertEqual(row['Cloud status'],'Synced')
        self.assertTrue(row['Evidence'].startswith("'="))
        self.assertEqual(row['Simulated'],'Yes')
    def test_recorded_sensor_snapshot_includes_surface(self):
        config=json.loads((pathlib.Path(__file__).resolve().parents[1]/'config.json').read_text())
        m=Monitor(config,self.store)
        import time
        m.surface={'time':time.time(),'label':'ice','distances':[3,2,.1],'margin':.8}
        m.command('start')
        m.ingest({'schema':'road-v1','tof_mm':580,'ax':0,'ay':0,'az':1,'gps_fix':False})
        row=next(r for r in self.store.pending() if r[3]=='sample')
        self.assertEqual(json.loads(row[4])['surface']['label'],'ice')
        m.surface['time']-=10
        m.ingest({'schema':'road-v1','tof_mm':580,'ax':0,'ay':0,'az':1,'gps_fix':False})
        with self.store.lock: payload=self.store.db.execute("SELECT payload FROM records WHERE kind='sample' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.assertIsNone(json.loads(payload)['surface'])
