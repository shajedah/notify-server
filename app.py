from gevent import monkey
monkey.patch_all()

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import gevent.queue
import gevent
import firebase_admin
from firebase_admin import credentials, messaging
import os

app = Flask(__name__)
CORS(app)

# ── Firebase Admin init ───────────────────────────────────────
cred = credentials.Certificate("firebase-key.json")
firebase_admin.initialize_app(cred)

# ── State ─────────────────────────────────────────────────────
state = {"online": False, "name": "", "device": ""}
subscribers = []       # SSE clients
fcm_tokens = set()     # registered Android devices

# ── Helpers ───────────────────────────────────────────────────
def push_sse(data):
    dead = []
    for q in subscribers:
        try:
            q.put_nowait(data)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in subscribers:
            subscribers.remove(q)

def send_fcm(device):
    """Send FCM push to all registered tokens."""
    if not fcm_tokens:
        return
    for token in list(fcm_tokens):
        try:
            msg = messaging.Message(
                data={"device": device, "msg": "is online"},
                token=token,
                android=messaging.AndroidConfig(
                    priority="high",
                    ttl=60  # expire after 60 seconds
                )
            )
            messaging.send(msg)
        except Exception as e:
            print(f"FCM error for token {token[:20]}...: {e}")
            # Remove invalid tokens
            if "registration-token-not-registered" in str(e):
                fcm_tokens.discard(token)

# ── Endpoints ─────────────────────────────────────────────────

@app.route("/notify", methods=["POST"])
def notify():
    data = request.get_json(force=True) or {}
    state["online"] = True
    state["name"]   = data.get("name", "Someone")
    state["device"] = data.get("device", "Unknown")

    # Push to SSE clients
    push_sse(f"data: online|{state['name']}|{state['device']}\n\n")

    # Push FCM to Android (app closed)
    gevent.spawn(send_fcm, state["device"])

    return jsonify({"ok": True})

@app.route("/register", methods=["POST"])
def register():
    """Android app registers its FCM token here."""
    data = request.get_json(force=True) or {}
    token = data.get("token", "").strip()
    if token:
        fcm_tokens.add(token)
        print(f"FCM token registered. Total: {len(fcm_tokens)}")
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
    q = gevent.queue.Queue()
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
    return jsonify({
        "ok": True,
        "sse_clients": len(subscribers),
        "fcm_tokens": len(fcm_tokens)
    })

@app.route("/")
def root():
    return jsonify({"ok": True})

if __name__ == "__main__":
    from gevent.pywsgi import WSGIServer
    print("Starting gevent WSGIServer on port 10000...")
    WSGIServer(("0.0.0.0", 10000), app).serve_forever()
