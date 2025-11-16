# test_server.py
# backend/test_server.py
# Minimal Socket.IO test server (aiohttp)
import asyncio
import json
import socketio
from aiohttp import web

sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
app = web.Application()
sio.attach(app)

@sio.event
async def connect(sid, environ):
    print("Client connected:", sid)

@sio.event
async def disconnect(sid):
    print("Client disconnected:", sid)

@sio.on("race_update")
async def on_race_update(sid, data):
    # print a compact summary to avoid flooding the console
    try:
        tick = data.get("tick")
        num = data.get("num_cars", len(data.get("cars", [])))
    except Exception:
        tick = None
        num = None
    print(f"[Server] race_update from {sid}: tick={tick} num_cars={num}")
    # optionally broadcast to connected clients (uncomment if you have a web UI)
    # await sio.emit("race_update", data, skip_sid=sid)

async def index(request):
    return web.Response(text="Telemetry test server (Socket.IO) is running.\n", content_type="text/plain")

app.router.add_get("/", index)

def main():
    # Use asyncio.run to start the aiohttp web server (clean event loop handling)
    web.run_app(app, host="127.0.0.1", port=8000)

if __name__ == "__main__":
    main()

