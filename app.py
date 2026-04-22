from gevent import monkey
monkey.patch_all()

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import gevent.queue
import gevent
import firebase_admin
from firebase_admin import credentials, messaging

app = Flask(__name__)
CORS(app)

# ── Firebase Admin init ───────────────────────────────────────
cred = credentials.Certificate("firebase-key.json")
firebase_admin.initialize_app(cred)

# ── State ─────────────────────────────────────────────────────
state      = {"online": False, "name": "", "device": ""}
subscribers = []
fcm_tokens  = set()

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
    """
    Send BOTH notification + data payload.
    - notification: OS shows it even if app is killed (like Telegram)
    - data: app can handle it when running for custom sound/vibration
    """
    if not fcm_tokens:
        return

    dead_tokens = []
    for token in list(fcm_tokens):
        try:
            msg = messaging.Message(
                # notification payload — OS handles this when app is killed
                notification=messaging.Notification(
                    title="🟢 Online",
                    body=f"{device} is online",
                ),
                # data payload — app handles this when running
                data={
                    "device": device,
                    "msg": "is online"
                },
                token=token,
                android=messaging.AndroidConfig(
                    priority="high",          # wake device immediately
                    notification=messaging.AndroidNotification(
                        channel_id="MomoAlertChannel",
                        priority="high",
                        default_sound=True,
                        default_vibrate_timings=False,
                        vibrate_timings_millis=[0, 200, 150, 200, 150, 200],
                        notification_count=1,
                        visibility="public",
                    )
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            alert=messaging.ApsAlert(
                                title="🟢 Online",
                                body=f"{device} is online"
                            ),
                            sound="default",
                            badge=1,
                            content_available=True,
                        )
                    )
                )
            )
            messaging.send(msg)
            print(f"FCM sent to {token[:20]}... device: {device}")
        except Exception as e:
            err = str(e)
            print(f"FCM error: {err}")
            if "registration-token-not-registered" in err or "invalid-registration-token" in err:
                dead_tokens.append(token)

    for t in dead_tokens:
        fcm_tokens.discard(t)

# ── Endpoints ─────────────────────────────────────────────────

@app.route("/")
def root():
    return jsonify({"ok": True})

@app.route("/notify", methods=["POST"])
def notify():
    data = request.get_json(force=True) or {}
    state["online"] = True
    state["name"]   = data.get("name", "Someone")
    state["device"] = data.get("device", "Unknown")

    push_sse(f"data: online|{state['name']}|{state['device']}\n\n")

    # Send FCM synchronously so errors are visible in logs
    print(f"[NOTIFY] device={state['device']} tokens={len(fcm_tokens)}")
    if fcm_tokens:
        dead = []
        for token in list(fcm_tokens):
            try:
                msg = messaging.Message(
                    notification=messaging.Notification(
                        title="🟢 Online",
                        body=f"{state['device']} is online",
                    ),
                    data={"device": state["device"]},
                    token=token,
                    android=messaging.AndroidConfig(
                        priority="high",
                        notification=messaging.AndroidNotification(
                            channel_id="momo_alerts",
                            priority="high",
                            default_sound=True,
                        )
                    )
                )
                result = messaging.send(msg)
                print(f"[FCM] OK: {result}")
            except Exception as e:
                print(f"[FCM] ERROR: {e}")
                if "not-registered" in str(e) or "invalid" in str(e).lower():
                    dead.append(token)
        for t in dead:
            fcm_tokens.discard(t)
    else:
        print("[FCM] No tokens — skipping")

    return jsonify({"ok": True})

@app.route("/register", methods=["POST"])
def register():
    data  = request.get_json(force=True) or {}
    token = data.get("token", "").strip()
    if token:
        fcm_tokens.add(token)
        print(f"Token registered. Total tokens: {len(fcm_tokens)}")
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
        "ok":         True,
        "sse_clients": len(subscribers),
        "fcm_tokens":  len(fcm_tokens)
    })

if __name__ == "__main__":
    from gevent.pywsgi import WSGIServer
    print("Starting gevent WSGIServer on port 10000...")
    WSGIServer(("0.0.0.0", 10000), app).serve_forever()
