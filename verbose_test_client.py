# verbose_test_client.py
import socketio
import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)

sio = socketio.AsyncClient(logger=True, engineio_logger=True)

@sio.event
async def connect():
    print("✅ Connected to backend")
    await sio.emit("start_race", {})

@sio.event
async def connect_error(data):
    print("❌ connect_error:", data)

@sio.event
async def race_update(data):
    print("🏎️  RACE UPDATE:", data)

@sio.event
async def race_complete(data):
    print("🏁 Race Complete:", data)
    await sio.disconnect()

@sio.event
async def disconnect():
    print("🔌 Disconnected from backend")

async def main():
    try:
        # try local loopback and both transports
        await sio.connect("http://127.0.0.1:8000", transports=['polling'])

        await sio.wait()
    except Exception as e:
        print("Exception on connect:", repr(e))

if __name__ == "__main__":
    asyncio.run(main())

