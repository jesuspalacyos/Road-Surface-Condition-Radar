"""Readable spreadsheet export shared by the browser endpoint and CLI."""
import csv
import io
import json
from datetime import datetime, timezone

HEADERS = ['Timestamp (UTC)', 'Session ID', 'Record type', 'Pothole candidate', 'Debris / raised object candidate', 'Surface match (experimental)', 'Verified hazard', 'Latitude (deg)', 'Longitude (deg)', 'Speed (km/h)', 'GPS fix', 'Satellites', 'Road distance (mm)', 'Road drop (mm)', 'Vibration (g)', 'Acceleration X (g)', 'Acceleration Y (g)', 'Acceleration Z (g)', 'Radar road returns', 'Radar height (mm)', 'Dry match distance', 'Wet match distance', 'Ice match distance', 'Separation margin (not probability)', 'Evidence', 'Simulated', 'Cloud status', 'Record ID']

def safe(value):
    if value is None: return ''
    if isinstance(value, bool): return 'Yes' if value else 'No'
    if isinstance(value, float): return round(value, 6)
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')): return "'" + value
    return value

def report_row(record):
    ident, session, timestamp, kind, payload, upload, synced = record
    d = json.loads(payload)
    sensor = d.get('sensor') or {}
    radar = d.get('radar') or {}
    surface = d if kind == 'surface' else d.get('surface') or {}
    if kind == 'surface': sensor = d.get('sensor') or {}
    alert = d.get('label') if kind == 'event' else d.get('current_alert')
    assessed = kind == 'event' or d.get('assessed', False)
    pothole = alert == 'Possible pothole' if assessed else None
    debris = alert == 'Possible raised object' if assessed else None
    distances = surface.get('distances') or []
    def distance(i): return distances[i] if len(distances)>i else None
    fix = sensor.get('gps_fix') is True
    lat = sensor.get('lat') if fix else (d.get('lat') if kind == 'event' else None)
    lon = sensor.get('lon') if fix else (d.get('lon') if kind == 'event' else None)
    row = [datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec='milliseconds'), session, kind, pothole, debris, surface.get('label'), False, lat, lon, sensor.get('speed_kmh') if fix else None, sensor.get('gps_fix'), sensor.get('satellites'), sensor.get('tof_mm'), d.get('depth_mm', sensor.get('depth_mm')), sensor.get('shock_g'), sensor.get('ax'), sensor.get('ay'), sensor.get('az'), radar.get('road_points'), radar.get('height_mm'), distance(0), distance(1), distance(2), surface.get('margin'), d.get('evidence'), d.get('demo', False), 'Synced' if synced else 'Queued' if upload else 'Local only', ident]
    return [safe(v) for v in row]

def iter_csv(store, session=None):
    # Keyset batches allow acquisition to continue during a long export.
    buf = io.StringIO(newline='')
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    yield '\ufeff' + buf.getvalue()
    with store.lock:
        maximum = store.db.execute('SELECT coalesce(max(rowid),0) FROM records').fetchone()[0]
    cursor = 0
    while cursor < maximum:
        sql = 'SELECT rowid,id,session,ts,kind,payload,upload,synced FROM records WHERE rowid>? AND rowid<=?'
        args = [cursor, maximum]
        if session: sql += ' AND session=?'; args.append(session)
        with store.lock:
            rows = store.db.execute(sql+' ORDER BY rowid LIMIT 500',args).fetchall()
        if not rows: break
        buf.seek(0); buf.truncate(0)
        for row in rows: writer.writerow(report_row(row[1:]))
        cursor = rows[-1][0]
        yield buf.getvalue()
