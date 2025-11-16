# view_replay.py
import sys
import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

def load_replay(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def flatten_replay(data):
    rows = []
    for tick_entry in data:
        tick = tick_entry.get("tick")
        run_id = tick_entry.get("run_id")
        ts = tick_entry.get("time")
        cars = tick_entry.get("cars", [])
        for c in cars:
            pos = c.get("position", None)
            px = py = None
            if isinstance(pos, (list, tuple)) and len(pos) >= 1:
                px = pos[0]
                py = pos[1] if len(pos) > 1 else None
            elif isinstance(pos, dict):
                px = pos.get("x")
                py = pos.get("y")
            rows.append({
                "run_id": run_id,
                "tick": tick,
                "time": ts,
                "car_id": c.get("id"),
                "pos_x": px,
                "pos_y": py,
                "speed": c.get("speed"),
                "lap_time": c.get("lap_time"),
                "lap_number": c.get("lap_number"),
                "status": c.get("status"),
                "position_diff": c.get("position_diff"),
            })
    df = pd.DataFrame(rows)
    return df

def summarize(df):
    print("Replay summary")
    print("--------------")
    print("Ticks:", df['tick'].nunique())
    print("Rows (car/tick records):", len(df))
    print("Cars:", df['car_id'].nunique(), list(df['car_id'].unique()))
    print()
    print("Per-car average speed:")
    print(df.groupby('car_id')['speed'].mean().sort_values(ascending=False).round(3))
    print()
    idx = df['speed'].idxmax() if 'speed' in df.columns and df['speed'].notnull().any() else None
    if idx is not None:
        row = df.loc[idx]
        print("Max speed:", row['speed'], "car:", row['car_id'], "tick:", row['tick'])
    print()

def save_csv(df, out_path):
    df.to_csv(out_path, index=False)
    print("Saved CSV:", out_path)

def plot_speeds(df, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cars = sorted(df['car_id'].dropna().unique())
    for car in cars:
        d = df[df['car_id'] == car].sort_values('tick')
        if d['speed'].dropna().empty:
            continue
        plt.figure()
        plt.plot(d['tick'], d['speed'])
        plt.title(f"Speed vs Tick — {car}")
        plt.xlabel("Tick")
        plt.ylabel("Speed")
        plt.grid(True)
        out_file = out_dir / f"{car}_speed.png"
        plt.savefig(out_file, bbox_inches='tight')
        plt.close()
        print("Wrote plot:", out_file)

def main():
    if len(sys.argv) < 2:
        print("Usage: python view_replay.py replay_file.json")
        sys.exit(1)
    path = sys.argv[1]
    data = load_replay(path)
    df = flatten_replay(data)
    summarize(df)
    csv_path = Path(path).with_suffix('.csv')
    save_csv(df, csv_path)
    plot_dir = Path("replay_plots")
    plot_speeds(df, plot_dir)
    print("Done. Plots in:", plot_dir.resolve())

if __name__ == "__main__":
    main()
