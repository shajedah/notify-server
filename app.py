from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import queue
import threading
import time

app = Flask(__name__)
CORS(app)

# In-memory state
state = {
    "online": False,
    "name": "",
    "device": ""
}

# SSE subscriber queues — one per connected client (ESP32, notify.py, etc.)
subscribers = []
subscribers_lock = threading.Lock()

def push_event(data: str):
    """Push event string to all connected SSE subscribers."""
    with subscribers_lock:
        dead = []
        for q in subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            subscribers.remove(q)

# POST /notify — chat app calls this when user logs in
@app.route("/notify", methods=["POST"])
def notify():
    data = request.get_json(force=True) or {}
    state["online"] = True
    state["name"]   = data.get("name", "Someone")
    state["device"] = data.get("device", "Unknown")
    # Push SSE event immediately to all listeners
    push_event(f"data: online|{state['name']}|{state['device']}\n\n")
    return jsonify({"ok": True})

# GET /status — polling fallback (notify.py uses this)
@app.route("/status", methods=["GET"])
def status():
    return jsonify(state)

# POST /clear — called after notification delivered
@app.route("/clear", methods=["POST"])
def clear():
    state["online"] = False
    state["name"]   = ""
    state["device"] = ""
    return jsonify({"ok": True})

# GET /events — SSE stream for ESP32 and any real-time client
@app.route("/events", methods=["GET"])
def events():
    q = queue.Queue(maxsize=10)
    with subscribers_lock:
        subscribers.append(q)

    def stream():
        # Send initial heartbeat so client knows connection is alive
        yield "data: heartbeat\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=20)  # 20s timeout = keepalive ping
                    yield msg
                except queue.Empty:
                    # Send keepalive ping every 20s to prevent timeout
                    yield "data: ping\n\n"
        except GeneratorExit:
            pass
        finally:
            with subscribers_lock:
                if q in subscribers:
                    subscribers.remove(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx buffering
            "Connection": "keep-alive"
        }
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, threaded=True)
