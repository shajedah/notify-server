from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# In-memory state
state = {
    "online": False,
    "name": "",
    "device": ""
}

# POST /notify — chat app calls this when user logs in
@app.route("/notify", methods=["POST"])
def notify():
    data = request.get_json()
    state["online"] = True
    state["name"] = data.get("name", "Someone")
    state["device"] = data.get("device", "Unknown")
    return jsonify({"ok": True})

# GET /status — notify.py polls this
@app.route("/status", methods=["GET"])
def status():
    return jsonify(state)

# POST /clear — notify.py calls this after notifying
@app.route("/clear", methods=["POST"])
def clear():
    state["online"] = False
    state["name"] = ""
    state["device"] = ""
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
