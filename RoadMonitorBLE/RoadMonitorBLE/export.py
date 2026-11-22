#!/usr/bin/env python3
"""Export persistent Pi history as CSV. Does not require Firebase or BLE."""
import argparse,csv,json,sqlite3
p=argparse.ArgumentParser();p.add_argument('--db',default='recordings.sqlite');p.add_argument('--out',default='recordings.csv');p.add_argument('--session');a=p.parse_args()
c=sqlite3.connect('file:'+a.db+'?mode=ro',uri=True)
query='SELECT id,session,ts,kind,payload,synced FROM records';args=[]
if a.session:query+=' WHERE session=?';args=[a.session]
with open(a.out,'w',newline='') as f:
 w=csv.writer(f);w.writerow(['id','session','unix_time','kind','data_json','cloud_synced'])
 w.writerows(c.execute(query+' ORDER BY ts',args))
print('Exported to',a.out)
