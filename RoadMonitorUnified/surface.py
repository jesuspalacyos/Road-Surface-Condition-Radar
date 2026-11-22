"""Experimental sample matching sharing the existing serial reader."""
import time
from collections import deque
import numpy as np
from radar_model import load_model, classify
from radar_decoder import Decoder

class Surface:
    def __init__(self, monitor):
        self.m = monitor
        self.model = load_model()
        self.meta = self.model[0]
        self.decoder = Decoder(self.meta['bins'])
        self.history = deque()
        self.started = None
        self.last = 0
    def feed(self, data):
        for frame, profile in self.decoder.feed(data):
            now = time.monotonic()
            if self.started is None: self.started = now
            self.history.append((now, profile[self.meta['indices']]))
            while self.history and now-self.history[0][0]>1: self.history.popleft()
            if now-self.started<1 or now-self.last<.2: continue
            x = np.median([v for _,v in self.history], axis=0)
            label, margin, distances = classify(x, self.model)
            result = dict(label=label, margin=margin, distances=distances.tolist(), bins=x.tolist(), frame=frame, time=time.time(), experimental=True)
            with self.m.lock:
                result['demo'] = self.m.demo
                result['sensor'] = self.m.sensor.copy() if time.monotonic()-self.m.sensor_at<2 else {}
                self.m.surface = result
                if self.m.recording: self.m.store.add(self.m.session, 'surface', result, True)
            self.last = now
