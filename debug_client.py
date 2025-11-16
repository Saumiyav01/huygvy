# backend/debug_client.py
# debug_client.py — verbose, pretty prints every incoming packet and shows a compact table per car
import asyncio
import json
import logging
from datetime import datetime

import socketio

logging.basicConfig(level=logging.INFO)
sio = socketio.AsyncClient(logger=True, engineio_logger=True)


def fmt(x, d=2):
    try:
        return f"{float(x):.{d}f}"
    except Exception:
        return str(x)


def now():
    return datetime.now().strftime("%H:%M:%S")


@sio.event
async def connect():
    print(f"[{now()}] ✅ CONNECTED to server")
    # request one short run (adjust series/laps/samples as you like)
    cfg = {"series": "both", "laps": 2, "mc_samples": 300, "emit_every_n_ticks": 2}
    await sio.emit("start_race", cfg)
    print(f"[{now()}] -> start_race emitted {cfg}")


@sio.event
async def race_started(data):
    print(f"[{now()}] 🏁 race_started: {data}")


@sio.event
async def race_update(data):
    # Pretty print full payload first (non-ascii allowed)
    print("\n" + "=" * 80)
    print(f"[{now()}] 🔄 race_update (full payload):")
    try:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        print("RAW:", data)

    # Then print compact human summary table
    cars = data.get("cars", []) or []
    session = data.get("session_id", "<no-session>")
    tick = data.get("tick", "?")
    env = data.get("env", {})
    events = data.get("events", {})

    header = f"[{now()}] Session={session} | Tick={tick} | rain={env.get('rain_intensity',0):.3f} temp={env.get('track_temp',0):.1f} | cars={len(cars)}"
    print(header)
    print("-" * len(header))
    print(f"{'CAR':22} {'S':3} {'Lap':4} {'AI(est)s':10} {'inc':6} {'ΔD':6} {'R_AI':6} {'Action':10} {'Conf':5}")
    print("-" * 80)
    for c in cars:
        cid = c.get("car_id", "")[:22]
        series = c.get("series", "")[:3]
        lap = c.get("lap", "")
        mc = c.get("mc_summary") or {}
        dec = c.get("decision") or {}
        ai_est = fmt(mc.get("lap_mean", 0.0), 2)
        inc = fmt(mc.get("incident_prob", 0.0), 3)
        delta_d = c.get("delta_D", c.get("ΔD", c.get("delta_D", None)))
        r_ai = fmt(c.get("R_AI", 0.0), 3)
        action = dec.get("action", "")
        conf = fmt(dec.get("confidence", 0.0), 2)
        print(f"{cid:22} {series:3} {str(lap):4} {ai_est:10} {inc:6} {str(delta_d):6} {r_ai:6} {action:10} {conf:5}")
    print("=" * 80 + "\n")


@sio.event
async def race_complete(data):
    print(f"[{now()}] 🏁 race_complete: {data}")
    # do not forcibly disconnect here — if you want automatic disconnect uncomment:
    # await sio.disconnect()


@sio.event
async def disconnect():
    print(f"[{now()}] 🔌 disconnected")


async def main():
    try:
        # explicit websocket transport works well locally
        await sio.connect("http://127.0.0.1:8000", transports=["websocket"])
        await sio.wait()
    except Exception as e:
        print(f"[{now()}] ERROR connecting or running client: {e}")


if __name__ == "__main__":
    asyncio.run(main())

