# main.py
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

# ----------------------------- CONFIG -----------------------------
EMIT_INTERVAL_S = 0.5  # minimum time between leaderboard emits
MAX_LEADERBOARD = 20    # number of top drivers to keep/emit
REPLAYS_DIR = "replays"
os.makedirs(REPLAYS_DIR, exist_ok=True)

# ----------------------------- SERVER SETUP -----------------------------
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = FastAPI(title="Race Sim Backend - Leaderboard & Sim Control")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Socket.IO ASGI app under /socket.io
socket_app = socketio.ASGIApp(sio)
app.mount("/socket.io", socket_app)

# ----------------------------- LEADERBOARD STATE -----------------------------
driver_states: Dict[str, Dict[str, Any]] = {}
leaderboard_lock = asyncio.Lock()
last_emit_ts: float = 0.0
_emit_task: Optional[asyncio.Task] = None

# ----------------------------- SIM RUN STATE -----------------------------
_current_run_id: Optional[str] = None
_current_replay: Optional[Dict[str, Any]] = None

# ----------------------------- UTILITIES -----------------------------


async def recompute_leaderboard() -> List[Dict[str, Any]]:
    """Return sorted leaderboard list (top MAX_LEADERBOARD)."""
    async with leaderboard_lock:
        drivers = list(driver_states.values())

    def sort_key(d: Dict[str, Any]):
        return (
            -int(d.get("completed_laps", 0)),
            int(d.get("position", 9999)),
            float(d.get("total_time", float("inf"))),
            float(d.get("best_lap", float("inf"))),
        )

    drivers.sort(key=sort_key)
    top = drivers[:MAX_LEADERBOARD]

    leaderboard = []
    for idx, d in enumerate(top, start=1):
        item = d.copy()
        item["rank"] = idx
        leaderboard.append(item)

    return leaderboard


async def schedule_emit_leaderboard():
    """Schedule a debounced leaderboard emit after EMIT_INTERVAL_S has passed."""
    global last_emit_ts, _emit_task

    now = time.time()
    elapsed = now - last_emit_ts
    remaining = max(0.0, EMIT_INTERVAL_S - elapsed)

    if _emit_task is not None and not _emit_task.done():
        return

    async def _delayed_emit(wait: float):
        global last_emit_ts, _emit_task
        try:
            if wait > 0:
                await asyncio.sleep(wait)
            leaderboard = await recompute_leaderboard()
            await sio.emit("leaderboard:update", {"leaderboard": leaderboard})
            last_emit_ts = time.time()
        finally:
            _emit_task = None

    _emit_task = asyncio.create_task(_delayed_emit(remaining))


async def process_telemetry_update(payload: Dict[str, Any], sid: Optional[str] = None):
    """
    Shared logic to handle telemetry payloads from Socket.IO or HTTP POST.
    Expects payload to contain at least 'driver_id'. Updates driver_states and schedules emit.
    """
    if not payload or "driver_id" not in payload:
        raise ValueError("missing driver_id in telemetry payload")

    driver_id = str(payload["driver_id"])

    async with leaderboard_lock:
        existing = driver_states.get(driver_id, {})
        updated = existing.copy()
        updated.update(payload)
        updated["last_update_ts"] = time.time()
        driver_states[driver_id] = updated

    # also append to current replay if present (non-blocking)
    if _current_replay is not None:
        try:
            # Keep small memory footprint: don't lock replay file for long
            _current_replay.setdefault("telemetry", []).append({
                "ts": int(time.time() * 1000),
                "driver_id": driver_id,
                "payload": payload
            })
        except Exception:
            # never break telemetry flow for replay errors
            pass

    await schedule_emit_leaderboard()

    # emit driver-specific update (to the sender room if provided)
    await sio.emit("driver:update", {"driver_id": driver_id, "state": driver_states[driver_id]}, room=sid)


# ----------------------------- SOCKET.IO EVENTS -----------------------------


@sio.event
async def connect(sid, environ, auth):
    print(f"[socket.io] Client connected: {sid}")
    await sio.emit("server:hello", {"msg": "welcome", "sid": sid}, room=sid)


@sio.event
async def disconnect(sid):
    print(f"[socket.io] Client disconnected: {sid}")


@sio.on("telemetry:update")
async def handle_telemetry_update(sid, data):
    try:
        await process_telemetry_update(data, sid=sid)
    except ValueError as e:
        await sio.emit("error", {"msg": str(e)}, room=sid)


@sio.on("leaderboard:subscribe")
async def handle_leaderboard_subscribe(sid, data):
    leaderboard = await recompute_leaderboard()
    await sio.emit("leaderboard:update", {"leaderboard": leaderboard}, room=sid)


@sio.on("leaderboard:reset")
async def handle_leaderboard_reset(sid, data):
    async with leaderboard_lock:
        driver_states.clear()
    await sio.emit("leaderboard:update", {"leaderboard": []})


# ----------------------------- FASTAPI ENDPOINTS -----------------------------


@app.get("/leaderboard")
async def get_leaderboard():
    lb = await recompute_leaderboard()
    return JSONResponse({"leaderboard": lb})


@app.post("/leaderboard/reset")
async def http_reset_leaderboard():
    async with leaderboard_lock:
        driver_states.clear()
    await sio.emit("leaderboard:update", {"leaderboard": []})
    return JSONResponse({"ok": True})


@app.get("/drivers/{driver_id}")
async def get_driver(driver_id: str):
    async with leaderboard_lock:
        d = driver_states.get(driver_id)
    if not d:
        raise HTTPException(status_code=404, detail="driver not found")
    return d


@app.post("/telemetry")
async def http_telemetry(request: Request):
    """
    Accept telemetry via plain HTTP POST from simulator scripts.
    Body should be JSON similar to Socket.IO telemetry payload.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    try:
        await process_telemetry_update(payload, sid=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse({"ok": True})


# ----------------------------- SIM CONTROL ENDPOINTS -----------------------------


def _mk_run_id(name: Optional[str] = None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if name:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40]
        return f"{safe}_{ts}"
    return f"run_{ts}"


@app.post("/api/sim/start")
async def start_simulation(request: Request):
    """
    Start a new simulation run. Accepts arbitrary JSON config ({} is fine).
    Saves <run_id>_config.json and creates a <run_id>.json replay skeleton.
    """
    global _current_run_id, _current_replay

    try:
        cfg = await request.json()
    except Exception:
        cfg = {}

    run_name = cfg.get("run_name")
    run_id = _mk_run_id(run_name)
    cfg["_meta"] = {"created_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id}

    cfg_path = os.path.join(REPLAYS_DIR, f"{run_id}_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    replay = {
        "run_id": run_id,
        "config": cfg,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "telemetry": [],
        "intent_predictions": [],
        "events": []
    }
    replay_path = os.path.join(REPLAYS_DIR, f"{run_id}.json")
    with open(replay_path, "w", encoding="utf-8") as f:
        json.dump(replay, f, indent=2)

    _current_run_id = run_id
    _current_replay = replay

    # announce to any connected clients that a new run started
    await sio.emit("sim:start", {"run_id": run_id, "config": cfg})

    return JSONResponse({"ok": True, "run_id": run_id, "replay_path": replay_path})


@app.get("/api/sim/current")
async def get_current_sim():
    return JSONResponse({"run_id": _current_run_id, "config": _current_replay.get("config") if _current_replay else None})
@app.get("/api/sim/config/{run_id}")
async def get_run_config(run_id: str):
    """
    Return saved run config for run_id if present in replays/<run_id>_config.json,
    or return the current in-memory config if it's the active run.
    """
    # check in-memory current
    if _current_run_id == run_id and _current_replay is not None:
        cfg = _current_replay.get("config")
        if cfg is not None:
            return JSONResponse(cfg)

    # otherwise try loading from disk
    cfg_path = os.path.join(REPLAYS_DIR, f"{run_id}_config.json")
    if not os.path.exists(cfg_path):
        raise HTTPException(status_code=404, detail="config not found")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return JSONResponse(cfg)



# ----------------------------- DEBUG / EXAMPLE -----------------------------


if __name__ == "__main__":
    import uvicorn

    # Default to port 8000 — change with --port if needed.
    uvicorn.run(app, host="0.0.0.0", port=8000)



# ----------------------------- DEBUG / EXAMPLE -----------------------------


if __name__ == "__main__":
    import uvicorn

    # Run the ASGI app directly. Use a different port if 8000 is occupied.
    uvicorn.run(app, host="0.0.0.0", port=8000)
