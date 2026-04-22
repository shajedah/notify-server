from gevent import monkey
monkey.patch_all()

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import gevent.queue

app = Flask(__name__)
CORS(app)

state = {"online": False, "name": "", "device": ""}
subscribers = []

def push_event(data):
    dead = []
    for q in subscribers:
        try:
            q.put_nowait(data)
        except Exception:
            dead.append(q)
    for q in dead:
        subscribers.remove(q)

@app.route("/notify", methods=["POST"])
def notify():
    data = request.get_json(force=True) or {}
    state["online"] = True
    state["name"]   = data.get("name", "Someone")
    state["device"] = data.get("device", "Unknown")
    push_event(f"data: online|{state['name']}|{state['device']}\n\n")
    return jsonify({"ok": True})

@app.route("/status", methods=["GET"])
def status():
    return jsonify(state)

@app.route("/clear", methods=["POST"])
def clear():
    state["online"] = False
    state["name"]   = ""
    state["device"] = ""
    return jsonify({"ok": True})

@app.route("/events", methods=["GET"])
def events():
    q = gevent.queue.Queue()  # NOT SimpleQueue — supports timeout
    subscribers.append(q)

    def stream():
        yield "data: heartbeat\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield msg
                except gevent.queue.Empty:
                    yield "data: ping\n\n"
        except GeneratorExit:
            pass
        finally:
            if q in subscribers:
                subscribers.remove(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        }
    )

@app.route("/health")
def health():
    return jsonify({"ok": True, "clients": len(subscribers)})
