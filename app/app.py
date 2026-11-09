import os, json, time, threading, datetime
from flask import Flask, jsonify

app = Flask(__name__)
TENANT = os.getenv("TENANT", "unknown")
VERSION = os.getenv("APP_VERSION", "dev")
KAFKA = os.getenv("KAFKA_BOOTSTRAP", "")


def publish_created():
    """Publish a WebsiteCreated event on startup (best effort)."""
    if not KAFKA:
        return
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA,
                          value_serializer=lambda v: json.dumps(v).encode())
        p.send("website-events", {
            "event": "WebsiteCreated", "tenant": TENANT, "version": VERSION,
            "source": "app", "ts": datetime.datetime.utcnow().isoformat() + "Z"})
        p.flush(5)
    except Exception as e:
        print("kafka publish failed:", e, flush=True)


threading.Thread(target=publish_created, daemon=True).start()


@app.route("/")
def index():
    return f"<h1>Hello from {TENANT}</h1><p>version {VERSION}</p>"


@app.route("/health")
def health():
    return jsonify(status="alive")


@app.route("/ready")
def ready():
    return jsonify(status="ready", tenant=TENANT)


@app.route("/load")
def load():
    """Burn CPU for ~0.3s so HPA has something to react to."""
    end = time.time() + 0.3
    while time.time() < end:
        sum(i * i for i in range(1000))
    return jsonify(status="done")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
