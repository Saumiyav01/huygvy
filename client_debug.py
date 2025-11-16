# client_debug.py — verbose Socket.IO client for diagnosing immediate disconnects
import asyncio
import sys
import socketio
import aiohttp
import logging

# On Windows avoid signal-handler warnings
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# Turn on verbose logging to see handshake and engineio reasons
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("client_debug")
# engineio/socketio use these names
logging.getLogger("engineio.client").setLevel(logging.DEBUG)
logging.getLogger("socketio.client").setLevel(logging.DEBUG)

SERVER_URL = "http://127.0.0.1:8000"
CONNECT_TIMEOUT = 8

async def run():
    session = aiohttp.ClientSession()
    # enable engineio/socketio internal logging by setting logger=True/engineio_logger=True
    sio = socketio.AsyncClient(logger=True, engineio_logger=True, reconnection=True, http_session=session)

    @sio.event
    async def connect():
        print("[client_debug] connected to server — socket id:", sio.sid)

    @sio.event
    async def disconnect():
        print("[client_debug] disconnected from server (client handler)")

    @sio.event
    async def connect_error(data):
        print("[client_debug] connect_error:", data)

    @sio.on("server_message")
    async def on_server_message(msg):
        print("[client_debug] server_message:", msg)

    @sio.on("race_update")
    async def on_race_update(msg):
        print("[client_debug] race_update:", msg)

    try:
        print("[client_debug] attempting connect to", SERVER_URL)
        try:
            await asyncio.wait_for(sio.connect(SERVER_URL, transports=["websocket"]), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            print("[client_debug] connect timed out")
            return
        except Exception as e:
            print("[client_debug] connect exception:", repr(e))
            return

        # keep running until manual cancel; print periodic alive marker
        print("[client_debug] now connected; waiting for server events. Press Ctrl+C to quit.")
        try:
            while True:
                await asyncio.sleep(5)
                # print heartbeat of local connection state
                print(f"[client_debug] heartbeat — connected={sio.connected}, sid={getattr(sio, 'sid', None)}")
                if not sio.connected:
                    print("[client_debug] socket not connected; will attempt to reconnect (socketio's reconnection=True handles this).")
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            print("[client_debug] interrupted by user")
    finally:
        try:
            # ensure clean disconnect and session close (prevents Unclosed client session)
            await sio.disconnect()
        except Exception:
            pass
        await session.close()
        print("[client_debug] shutdown complete (session closed)")

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("[client_debug] stopped by KeyboardInterrupt")
