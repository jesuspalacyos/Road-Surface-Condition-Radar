#!/usr/bin/env python3
"""Serve only on this computer; no third-party Python packages required."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import webbrowser

URL = 'http://localhost:8000/dashboard.html'
def open_page():
    if sys.platform == 'darwin':
        result = subprocess.run(['open', '-a', 'Google Chrome', URL], capture_output=True)
        if result.returncode == 0:
            return
    webbrowser.open(URL)

if __name__ == '__main__':
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).resolve().parent))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 8000), handler)
    except OSError as error:
        print(f'Cannot start the dashboard: {error}\nClose another server using port 8000, then retry.')
        sys.exit(1)
    print(f'Open in Google Chrome: {URL}\nKeep this Terminal open. Press Control+C to stop.')
    timer = threading.Timer(1, open_page)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
