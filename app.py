from gevent import monkey
monkey.patch_all()  # MUST be first line — patches all blocking calls

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import gevent.queue
import gevent

app = Flask(__name__)
CORS(app)

# In-memory state
state = {
    "online": False,
    "name": "",
    "device": ""
}

# SSE subscribers — one gevent Queue per connected client
subscribers = []

def push_event(data: str):
    dead = []
    for q in subscribers:
        try:
            q.put_nowait(data)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in subscribers:
            subscribers.remove(q)

# POST /notify — chat app calls this on login
@app.route("/notify", methods=["POST"])
def notify():
    data = request.get_json(force=True) or {}
    state["online"] = True
    state["name"]   = data.get("name", "Someone")
    state["device"] = data.get("device", "Unknown")
    push_event(f"data: online|{state['name']}|{state['device']}\n\n")
    return jsonify({"ok": True})

# GET /status — polling fallback
@app.route("/status", methods=["GET"])
def status():
    return jsonify(state)

# POST /clear — reset after notification delivered
@app.route("/clear", methods=["POST"])
def clear():
    state["online"] = False
    state["name"]   = ""
    state["device"] = ""
    return jsonify({"ok": True})

# GET /events — SSE stream (gevent-powered, no timeout)
@app.route("/events", methods=["GET"])
def events():
    q = gevent.queue.Queue()
    subscribers.append(q)

    def stream():
        yield "data: heartbeat\n\n"
        try:
            while True:
                try:
                    # Block with gevent — no thread blocking, no worker timeout
                    msg = q.get(timeout=25)
                    yield msg
                except gevent.queue.Empty:
                    yield "data: ping\n\n"  # keepalive every 25s
        except GeneratorExit:
            pass
        finally:
            if q in subscribers:
                subscribers.remove(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        }
    )

@app.route("/health")
def health():
    return jsonify({"ok": True, "clients": len(subscribers)})
