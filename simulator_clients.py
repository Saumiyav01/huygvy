"""
simulator_clients.py

Simulates multiple drivers based on the backend-run configuration.
Usage:
  python simulator_clients.py --run-id <run_id>
If --run-id omitted, it will try to use /api/sim/current to find the active run_id.

This edited version has the global declarations fixed and is cleaned up.
"""

import threading
import time
import random
import argparse
import requests
import math
import sys

# Configuration: backend URL (change if your backend runs elsewhere)
BACKEND_HOST = "http://127.0.0.1:8000"
GET_CONFIG_ENDPOINT = "/api/sim/config/{}"
GET_CURRENT_ENDPOINT = "/api/sim/current"
TELEMETRY_ENDPOINT = "/telemetry"

# Simulation tick (ms)
TICK_MS = 300

# Simple mapping: tyre compound -> base_speed_delta, wear_rate
TYRE_PROFILE = {
    "soft":    {"speed_delta": +1.8, "wear_rate": 0.018, "warmup": 1.1},
    "medium":  {"speed_delta": +0.6, "wear_rate": 0.012, "warmup": 1.0},
    "hard":    {"speed_delta": -0.6, "wear_rate": 0.007, "warmup": 0.9},
    "inter":   {"speed_delta": -0.4, "wear_rate": 0.010, "warmup": 0.95},
    "wet":     {"speed_delta": -1.2, "wear_rate": 0.020, "warmup": 1.2},
}
# Aggression mode -> throttle bias, brake bias, risk factor (chance to crash or make mistake)
AGGRESSION_PROFILE = {
    "calm":      {"throttle_bias": 0.8, "brake_bias": 1.1, "risk": 0.005},
    "balanced":  {"throttle_bias": 1.0, "brake_bias": 1.0, "risk": 0.01},
    "overdrive": {"throttle_bias": 1.15, "brake_bias": 0.85, "risk": 0.03},
    "ai_adaptive":{"throttle_bias": 1.0, "brake_bias": 1.0, "risk": 0.012},
}
# Strategy approximate pit lap offsets
STRATEGY_PIT_OFFSET = {
    "undercut": -3,   # tends to pit earlier
    "overcut": +4,    # tends to pit later
    "standard": 0,
    "attack": -2,
    "defensive": +1,
    "weather_dependent": 0,
}

# Safety: clamp helpers
def clamp(v, a, b):
    return max(a, min(b, v))

# DriverState holds runtime dynamic values
class DriverState:
    def __init__(self, driver_id, cfg, global_cfg):
        self.driver_id = driver_id
        self.cfg = cfg or {}
        self.global_cfg = global_cfg or {}
        # runtime merged params (apply defaults)
        self.base_speed = float(self.cfg.get("base_speed", self.global_cfg.get("base_speed", 45.0)))
        tyre = self.cfg.get("tyre_compound") or self.global_cfg.get("tyre_compound") or "medium"
        self.tyre_compound = tyre if tyre in TYRE_PROFILE else "medium"
        self.aggression = self.cfg.get("aggression_mode") or self.global_cfg.get("aggression_mode") or "balanced"
        if self.aggression not in AGGRESSION_PROFILE:
            self.aggression = "balanced"
        self.strategy = self.cfg.get("strategy") or self.global_cfg.get("strategy") or "standard"
        self.thermal = self.cfg.get("thermal_rate") or self.global_cfg.get("thermal_rate") or "optimal"

        # dynamic state
        self.tyre_wear = 0.0           # cumulative wear
        self.tyre_temp = 30.0         # degrees C
        self.lap = 0
        self.lap_progress = 0.0
        self.position_x = random.uniform(0,500)
        self.position_y = random.uniform(0,500)
        self.yaw = 0.0
        self.in_pit = False
        self.pit_cooldown = 0         # ticks left for pit stop
        self.next_pit_lap = None      # plan next pit lap based on strategy
        self.random = random.Random()
        # seed optionally per driver if provided
        seed = self.cfg.get("seed") or self.global_cfg.get("seed")
        if seed is not None:
            try:
                sid = f"{seed}_{driver_id}"
                self.random.seed(hash(sid) & 0xffffffff)
            except Exception:
                pass

    def plan_pit_lap(self, total_laps):
        # Basic heuristic: plan mid-race or based on strategy offset
        base = max(1, int(total_laps * 0.4))
        offset = STRATEGY_PIT_OFFSET.get(self.strategy, 0)
        planned = clamp(base + offset + int(self.random.uniform(-2,2)), 1, total_laps)
        self.next_pit_lap = planned

# Simulate one tick for a driver and return telemetry dict
def simulate_tick(state: DriverState, cfg_run: dict, tick_ms=TICK_MS):
    # 1) compute throttle & brake influenced by aggression
    ag = AGGRESSION_PROFILE[state.aggression]
    # small random fluctuation
    throttle_pct = clamp(state.random.gauss(50 * ag["throttle_bias"], 12), 0, 100)
    brake_pct = clamp(state.random.gauss(10 * ag["brake_bias"], 8), 0, 100)

    # 2) tyre profile effects
    tyre_info = TYRE_PROFILE.get(state.tyre_compound, TYRE_PROFILE["medium"])
    base_speed = state.base_speed + tyre_info["speed_delta"]  # base m/s influenced by tyre
    # thermal influence: hot -> quicker warmup but faster wear; cold -> slower grip
    thermal_factor = 1.0
    if state.thermal == "hot":
        thermal_factor = 1.05
    elif state.thermal == "cool":
        thermal_factor = 0.97
    elif state.thermal == "cold":
        thermal_factor = 0.92
    elif state.thermal == "optimal":
        thermal_factor = 1.0

    # speed loss due to tyre wear (grip loss)
    speed_loss = 0.12 * state.tyre_wear   # tuneable constant
    # random noise
    noise = state.random.uniform(-1.5, 1.5)

    # current speed
    speed_mps = clamp((base_speed * thermal_factor) * (throttle_pct/100.0) - speed_loss + noise, 5.0, 80.0)

    # 3) tyre wear accumulation depends on throttle and tyre wear rate
    wear_rate = tyre_info["wear_rate"] * (1.0 + (throttle_pct/100.0)) * (1.0 + (0.05 if state.thermal=="hot" else 0.0))
    # aggression increases wear slightly
    wear_rate *= (1.0 + (0.12 if state.aggression == "overdrive" else 0.0))
    state.tyre_wear += wear_rate * (tick_ms/1000.0)

    # 4) tyre temp evolves: increases with throttle and with wear
    temp_rise = (throttle_pct/100.0) * (1.0 + state.tyre_wear) * tyre_info["warmup"] * 0.8
    state.tyre_temp = max(20.0, state.tyre_temp + temp_rise * (tick_ms/1000.0))

    # 5) lap progress update (simplified)
    # assume track length corresponds to a lap_time proportional to speed.
    # Convert speed to a lap_progress delta:
    # faster speed -> larger progress increment per tick.
    progress_delta = (speed_mps / 60.0) * (tick_ms/1000.0) * 0.01  # tuned scaling
    state.lap_progress += progress_delta
    if state.lap_progress >= 1.0:
        state.lap += 1
        state.lap_progress -= 1.0
        # if next_pit_lap not planned, plan now (first lap planning)
        if state.next_pit_lap is None and cfg_run:
            total_laps = cfg_run.get("total_laps") or cfg_run.get("num_laps") or cfg_run.get("duration_seconds", 0)
            if total_laps:
                state.plan_pit_lap(total_laps)

    # 6) Pit logic: enter pit if planned and on lap
    # simplistic pit duration based on strategy and tyre change
    if state.next_pit_lap is not None and state.lap >= state.next_pit_lap and not state.in_pit:
        # Enter pit
        state.in_pit = True
        # pit_time base (seconds)
        pit_base = float(state.cfg.get("pit_time_sec", state.global_cfg.get("pit_time_sec", 20.0)))
        # strategy may shorten or lengthen stationary pit
        if state.strategy == "undercut":
            pit_base *= 0.95
        elif state.strategy == "overcut":
            pit_base *= 1.05
        # convert to ticks
        state.pit_cooldown = max(1, int((pit_base * 1000.0) / tick_ms))
        # while in pit, speed will be very low and lap_progress slowed
    if state.in_pit:
        state.pit_cooldown -= 1
        # while in pit set minimal speed and braking slightly higher
        speed_mps = 1.0
        throttle_pct = 0.0
        brake_pct = 20.0
        if state.pit_cooldown <= 0:
            state.in_pit = False
            # plan no more pits by setting next_pit_lap far in the future
            state.next_pit_lap = (state.lap + 999)

    # 7) Crash / incident chance influenced by aggression and risk
    base_crash_prob = 0.0005
    risk = AGGRESSION_PROFILE[state.aggression]["risk"]
    crash_roll = state.random.random()
    incident = None
    if crash_roll < (base_crash_prob + risk * 0.001):
        # small incident: spin or minor crash that slows driver for a few ticks
        incident = {"type": "spin", "severity": state.random.uniform(0.1, 0.6)}
        # apply effect: drop speed & increase brake for few ticks
        speed_mps = max(3.0, speed_mps * (1.0 - incident["severity"]))
        brake_pct = min(100.0, brake_pct + 30.0)

    # 8) build telemetry packet
    now_ms = int(time.time() * 1000)
    pkt = {
        "driver_id": state.driver_id,
        "timestamp_ms": now_ms,
        "lap": state.lap,
        "lap_progress": round(state.lap_progress, 4),
        "speed_mps": round(speed_mps, 3),
        "position_x": round(state.position_x + state.lap_progress*5.0, 3),
        "position_y": round(state.position_y + state.lap_progress*2.0, 3),
        "yaw": round(state.yaw, 3),
        "throttle_pct": round(throttle_pct, 2),
        "brake_pct": round(brake_pct, 2),
        "tyre_temp": round(state.tyre_temp, 2),
        # optional: expose internal state for analytics
        "tyre_compound": state.tyre_compound,
        "tyre_wear": round(state.tyre_wear, 4),
        "in_pit": state.in_pit,
        "strategy": state.strategy
    }
    # return pkt and any local incident discovered
    return pkt, incident

# Worker thread: sends telemetry continuously
def driver_loop(driver_id, state: DriverState, cfg_run, stop_event):
    url = BACKEND_HOST + TELEMETRY_ENDPOINT
    while not stop_event.is_set():
        pkt, incident = simulate_tick(state, cfg_run, TICK_MS)
        try:
            r = requests.post(url, json=pkt, timeout=1.0)
            if r.status_code == 200:
                body = r.json()
                # backend returns predicted intent in response
                intent = body.get("predicted_intent") or body.get("intent")
                conf = body.get("confidence") or 0.0
                print(f"[{driver_id}] lap={pkt['lap']} prog={pkt['lap_progress']} speed={pkt['speed_mps']} intent={intent} conf={conf:.2f}")
            else:
                print(f"[{driver_id}] HTTP {r.status_code} {r.text}")
        except Exception as e:
            print(f"[{driver_id}] error: {e}")
        # small sleep until next tick
        time.sleep(TICK_MS / 1000.0)

# Main: fetch config and launch drivers
def main():
    global BACKEND_HOST, TICK_MS   # <<< MUST be the very first line inside main()

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=str, default=None, help="run_id from /api/sim/start (optional)")
    parser.add_argument("--host", type=str, default=BACKEND_HOST, help="backend host (includes protocol and port)")
    parser.add_argument("--tick-ms", type=int, default=300, help="tick in ms")
    args = parser.parse_args()

    BACKEND_HOST = args.host
    TICK_MS = args.tick_ms

    # find active run config
    run_id = args.run_id
    cfg = None
    if run_id is None:
        # ask backend for current run
        try:
            r = requests.get(BACKEND_HOST + GET_CURRENT_ENDPOINT, timeout=2.0)
            r.raise_for_status()
            info = r.json()
            run_id = info.get("run_id")
            if run_id:
                print(f"Discovered active run_id: {run_id}")
        except Exception as e:
            print("No run_id provided and /api/sim/current failed:", e)
            print("Exiting.")
            sys.exit(1)

    # fetch full config
    try:
        r = requests.get(BACKEND_HOST + GET_CONFIG_ENDPOINT.format(run_id), timeout=3.0)
        r.raise_for_status()
        cfg = r.json()
    except Exception as e:
        print("Failed to fetch run config:", e)
        sys.exit(1)

    print("Loaded run config:", cfg.get("_meta", {}).get("run_id", run_id))

    # read drivers map
    drivers_map = cfg.get("drivers", {})
    num_cars = cfg.get("num_cars", len(drivers_map))

    if len(drivers_map) < num_cars:
        for i in range(1, num_cars + 1):
            did = f"driver_{i:02d}"
            if did not in drivers_map:
                drivers_map[did] = {}

    # global defaults
    global_defaults = cfg.get("global", {})

    # create and start threads
    stop_event = threading.Event()
    threads = []
    states = {}
    for did, dcfg in drivers_map.items():
        state = DriverState(did, dcfg, global_defaults)
        states[did] = state

        t = threading.Thread(target=driver_loop, args=(did, state, cfg, stop_event), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.05)  # stagger startup slightly

    print(f"Started {len(threads)} simulated drivers. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopping simulator...")
        stop_event.set()
        time.sleep(0.5)
        print("Simulator stopped.")


if __name__ == "__main__":
    main()
