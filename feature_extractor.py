# feature_extractor.py
from collections import deque, defaultdict
import numpy as np
from typing import Dict

class DriverWindow:
    def __init__(self, maxlen=40):
        # Keep last N packets per driver (40 is a good default ~seconds depends on tick)
        self.buf = deque(maxlen=maxlen)

    def push(self, pkt: dict):
        self.buf.append(pkt)

    def is_ready(self, min_samples=5):
        return len(self.buf) >= min_samples

    def to_features(self) -> Dict:
        arr = np.array([
            [p.get('speed_mps',0.0), p.get('throttle_pct',0.0), p.get('brake_pct',0.0),
             p.get('tyre_temp',0.0), p.get('lap_progress',0.0)]
            for p in self.buf
        ])
        if arr.size == 0:
            return {}
        means = arr.mean(axis=0).tolist()
        stds  = arr.std(axis=0).tolist()
        delta_speed = float(arr[-1,0] - means[0])
        lap_progress = arr[:,4]
        if len(lap_progress) >= 2:
            prog_slope = float((lap_progress[-1] - lap_progress[0]) / max(len(lap_progress)-1,1))
        else:
            prog_slope = 0.0
        features = {
            "speed_mean": float(means[0]),
            "speed_std": float(stds[0]),
            "delta_speed": delta_speed,
            "throttle_mean": float(means[1]),
            "brake_mean": float(means[2]),
            "tyre_temp_mean": float(means[3]),
            "lapprog_slope": prog_slope,
            "samples": len(self.buf)
        }
        return features

class FeatureExtractor:
    def __init__(self):
        self.windows: Dict[str, DriverWindow] = defaultdict(DriverWindow)

    def push(self, telemetry: dict):
        did = telemetry['driver_id']
        self.windows[did].push(telemetry)
        return self.windows[did]

    def get_features(self, driver_id: str, min_samples=5):
        w = self.windows.get(driver_id)
        if not w or not w.is_ready(min_samples=min_samples):
            return {}
        return w.to_features()
