# client.py
import asyncio
import socketio
import aiohttp
import sys
import time

# On Windows, selecting SelectorEventLoop avoids some signal/Proactor issues:
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

SERVER_URL = "http://127.0.0.1:8000"  # adjust if needed
RETRY_MAX = 5
RETRY_DELAY = 1.5  # seconds

async def main():
    # Create a shared aiohttp session and pass it to socketio AsyncClient
    session = aiohttp.ClientSession()
    sio = socketio.AsyncClient(logger=False, engineio_logger=False, http_session=session, reconnection=False)

    @sio.event
    async def connect():
        print("[client] connected to server.")

    @sio.event
    async def disconnect():
        print("[client] disconnected from server.")

    @sio.event
    async def connect_error(data):
        print("[client] connection failed:", data)

    # Example custom event handler (adjust to your server's events):
    @sio.on("race_update")
    async def on_race_update(msg):
        print("[client] race_update:", msg)

    # Attempt connection with limited retries
    connected = False
    last_exc = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            print(f"[client] Attempt {attempt} connecting to {SERVER_URL} ...")
            # transports=['websocket'] forces ws (avoid polling fallback)
            await sio.connect(SERVER_URL, transports=["websocket"])
            connected = True
            break
        except Exception as e:
            last_exc = e
            print(f"[client] Connection attempt {attempt} failed: {e}")
            # small backoff
            await asyncio.sleep(RETRY_DELAY * attempt)

    if not connected:
        print("[client] ERROR connecting or running client: giving up after retries.", last_exc)
        # ensure we close resources
        try:
            await sio.disconnect()
        except Exception:
            pass
        await session.close()
        return

    # Example: stay connected for N seconds or until interrupted
    try:
        # keep alive; the server may send events to handlers above
        await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print("[client] interrupted by user")
    finally:
        # clean shutdown — IMPORTANT to avoid unclosed client session warning
        try:
            await sio.disconnect()
        except Exception:
            pass
        await session.close()
        print("[client] shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[client] stopped by KeyboardInterrupt")
