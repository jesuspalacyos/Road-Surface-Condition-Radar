#!/usr/bin/env python3
"""Export flat, Excel-friendly telemetry from the Pi database."""
import argparse
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from reporting import iter_csv

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', default=str(Path(__file__).with_name('recordings.sqlite')))
    p.add_argument('--out', default='roadsense-recordings.csv')
    p.add_argument('--session')
    a = p.parse_args()
    db = sqlite3.connect(Path(a.db).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        with open(a.out,'w',newline='',encoding='utf-8') as f:
            for chunk in iter_csv(SimpleNamespace(db=db,lock=threading.RLock()),a.session): f.write(chunk)
    finally: db.close()
    print('Exported to',a.out)
if __name__ == '__main__': main()
