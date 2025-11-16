# intent_service.py
import asyncio
import json
import os
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
import uvicorn
from telemetry_schema import TelemetryPacket
from feature_extractor import FeatureExtractor
from intent_predictor import IntentPredictor

app = FastAPI()
fe = FeatureExtractor()
predictor = IntentPredictor()

# In-memory state
leaderboard = {}      # driver_id -> latest simple summary
clients = set()       # connected viewer websockets
leaderboard_lock = asyncio.Lock()
clients_lock = asyncio.Lock()

# Replay folder and run tracking
REPLAY_DIR = "replays"
os.makedirs(REPLAY_DIR, exist_ok=True)
current_run_id = None
current_replay = None
replay_lock = asyncio.Lock()

def start_new_run(run_name=None):
    global current_run_id, current_replay
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    current_run_id = run_name or f"run_{ts}"
    path = os.path.join(REPLAY_DIR, f"{current_run_id}.json")
    current_replay = {
        "run_id": current_run_id,
        "started_at": ts,
        "telemetry": [],
        "intent_predictions": [],
        "events": []
    }
    return current_run_id

# Start a default run automatically
start_new_run()

# broadcast to all connected websockets
async def broadcast_json(message: dict):
    async with clients_lock:
        to_remove = []
        for ws in list(clients):
            try:
                await ws.send_json(message)
            except Exception:
                to_remove.append(ws)
        for r in to_remove:
            clients.remove(r)

@app.post("/telemetry")
async def ingest_telemetry(payload: dict):
    # Validate incoming packet
    try:
        pkt = TelemetryPacket(**payload).dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    driver_id = pkt["driver_id"]
    ts = pkt["timestamp_ms"]

    # Update leaderboard snapshot
    async with leaderboard_lock:
        leaderboard[driver_id] = {
            "driver_id": driver_id,
            "ts_ms": ts,
            "lap": pkt["lap"],
            "lap_progress": pkt["lap_progress"],
            "speed_mps": pkt["speed_mps"]
        }

    # Push into feature extractor
    fe.push(pkt)

    # Get features (if enough samples)
    features = fe.get_features(driver_id, min_samples=5)

    # Predict intent
    intent, probs, confidence = predictor.predict(features)

    # Build intent message
    intent_msg = {
        "type": "intent",
        "ts_ms": ts,
        "driver_id": driver_id,
        "intent": intent,
        "probabilities": probs,
        "confidence": confidence,
        "model_version": "intent-rules-v1"
    }

    # Append telemetry and intent to replay
    async with replay_lock:
        current_replay["telemetry"].append(pkt)
        current_replay["intent_predictions"].append({
            "ts_ms": ts,
            "driver_id": driver_id,
            "intent": intent,
            "probabilities": probs,
            "confidence": confidence,
            "features": features
        })
        # occasional flush to disk
        if len(current_replay["telemetry"]) % 200 == 0:
            path = os.path.join(REPLAY_DIR, f"{current_run_id}.json")
            with open(path, "w") as f:
                json.dump(current_replay, f)

    # Broadcast leaderboard snapshot and intent
    lb_snapshot = {"type":"leaderboard", "ts_ms": ts, "data": list(leaderboard.values())}
    await broadcast_json(lb_snapshot)
    await broadcast_json(intent_msg)

    return {"ok": True, "predicted_intent": intent, "confidence": confidence}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    async with clients_lock:
        clients.add(ws)
    try:
        # send current leaderboard snapshot once
        async with leaderboard_lock:
            await ws.send_json({"type":"leaderboard","ts_ms":0,"data":list(leaderboard.values())})
        while True:
            # keep connection alive; optionally accept viewer messages
            await ws.receive_text()
    except WebSocketDisconnect:
        async with clients_lock:
            if ws in clients:
                clients.remove(ws)
    except Exception:
        async with clients_lock:
            if ws in clients:
                clients.remove(ws)

@app.get("/replay/current")
async def get_current_replay():
    async with replay_lock:
        return current_replay

@app.post("/replay/save")
async def save_replay_and_start_new(name: str = None):
    async with replay_lock:
        path = os.path.join(REPLAY_DIR, f"{current_run_id}.json")
        with open(path, "w") as f:
            json.dump(current_replay, f, indent=2)
        start_new_run(run_name=name)
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("intent_service:app", host="0.0.0.0", port=8000)
