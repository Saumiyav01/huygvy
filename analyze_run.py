# backend/analyze_run.py
"""
Post-race analytics for replay_XXXX.json files.
Generates:
- lap time chart
- speed trend chart
- event timeline
- decision histogram
- risk reward curve (if available)
All outputs saved to backend/analytics_output/
"""

import json
import os
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

OUTPUT_DIR = Path("analytics_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# -----------------------------
# Load replay file
# -----------------------------
def load_replay(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# -----------------------------
# Extract timeseries
# -----------------------------
def extract_timeseries(replay):
    ticks = []
    lap_times = {}
    speeds = {}
    decisions = {}
    events = []

    for entry in replay:
        tick = entry["tick"]
        ticks.append(tick)

        # per car values
        for car in entry["cars"]:
            cid = car["id"]

            # lap time
            lap_times.setdefault(cid, []).append(car["lap_time"])

            # speed
            speeds.setdefault(cid, []).append(car["speed"])

        # decisions
        for cid, d in entry["decisions"].items():
            decisions.setdefault(cid, []).append(d["action"])

        # events
        if entry.get("events"):
            events.append((tick, entry["events"]))

    return ticks, lap_times, speeds, decisions, events

# -----------------------------
# Plot helper
# -----------------------------
def save_plot(name, fig):
    out = OUTPUT_DIR / name
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"[analytics] saved: {out}")

# -----------------------------
# Visualization
# -----------------------------
def plot_lap_times(ticks, lap_times):
    fig = plt.figure(figsize=(10, 4))
    for cid, series in lap_times.items():
        plt.plot(ticks, series, label=cid)
    plt.title("Lap Time Over Race")
    plt.xlabel("Tick")
    plt.ylabel("Lap Time")
    plt.legend()
    save_plot("lap_times.png", fig)

def plot_speeds(ticks, speeds):
    fig = plt.figure(figsize=(10, 4))
    for cid, series in speeds.items():
        plt.plot(ticks, series, label=cid)
    plt.title("Car Speed Over Time")
    plt.xlabel("Tick")
    plt.ylabel("Speed")
    plt.legend()
    save_plot("speeds.png", fig)

def plot_decisions(decisions):
    fig = plt.figure(figsize=(8, 4))
    labels = ["push", "normal", "conserve"]
    counts = [0, 0, 0]

    for cid, seq in decisions.items():
        for a in seq:
            if a == "push": counts[0] += 1
            elif a == "normal": counts[1] += 1
            else: counts[2] += 1

    plt.bar(labels, counts)
    plt.title("Decision Distribution Across Race")
    save_plot("decision_histogram.png", fig)

def plot_event_timeline(events):
    fig = plt.figure(figsize=(10, 3))
    ys = []
    xs = []

    for tick, ev in events:
        xs.append(tick)
        ys.append(len(ev.get("new_events", [])))

    plt.stem(xs, ys)
    plt.title("Event Timeline (Crashes / Safety Car)")
    plt.xlabel("Tick")
    plt.ylabel("New Events")
    save_plot("event_timeline.png", fig)

# -----------------------------
# Run
# -----------------------------
def analyze(replay_path):
    print(f"[analytics] Loading replay: {replay_path}")
    replay = load_replay(replay_path)

    ticks, lap_times, speeds, decisions, events = extract_timeseries(replay)

    print("[analytics] Generating plots...")
    plot_lap_times(ticks, lap_times)
    plot_speeds(ticks, speeds)
    plot_decisions(decisions)
    plot_event_timeline(events)

    print("\n[analytics] Done! Files saved to analytics_output/")

# -----------------------------
# CLI
# -----------------------------
if __name__ == "__main__":
    # auto-detect latest replay_*.json
    files = list(Path(".").glob("replay_*.json"))
    if not files:
        print("No replay_*.json found in backend folder!")
        exit()

    latest = max(files, key=lambda f: f.stat().st_mtime)
    print(f"[analytics] Auto-selected latest replay: {latest}")

    analyze(str(latest))
