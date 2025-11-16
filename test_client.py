# backend/test_client.py (aggregated client)
# test_client.py
import socketio

sio = socketio.Client(logger=True, engineio_logger=True)

@sio.event
def connect():
    print("✅ Connected to backend")

@sio.event
def disconnect():
    print("❌ Disconnected from backend")

@sio.on("race_update")
def on_race_update(data):
    try:
        print(f"[Client] race_update: tick={data.get('tick')} num_cars={data.get('num_cars', len(data.get('cars', [])))}")
    except Exception:
        print("[Client] race_update received (unprintable)")

if __name__ == "__main__":
    sio.connect("http://127.0.0.1:8000")
    print("Listening for race_update... (CTRL+C to quit)")
    sio.wait()

