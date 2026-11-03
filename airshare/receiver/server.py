"""Flask-based receiver server for AirShare."""
import os
import logging
import threading
import socket
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory

from airshare import config
from airshare.receiver.storage import StorageManager
from airshare.receiver.discovery import DiscoveryBroadcaster
from airshare.shared.protocol import TransferResponse
from airshare.shared.pairing import PairingStore, generate_pin, generate_token

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

storage = StorageManager()
pairing = PairingStore()
connected_senders = set()
_device_name = "AirShare Receiver"
_pin = generate_pin()
_lock = threading.Lock()


def _get_local_ip():
    """Get the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.route("/")
def index():
    """Dashboard page."""
    return render_template("index.html", device_name=_device_name, pin=_pin)


@app.route("/api/pair", methods=["POST"])
def api_pair():
    """Pair a sender using the dashboard PIN and issue a per-peer token."""
    data = request.get_json(silent=True) or {}
    pin = data.get("pin", "")
    device_id = data.get("device_id", "")
    device_name = data.get("device_name", "Unknown")

    if not pin or not device_id:
        return jsonify({"success": False, "error": "pin and device_id required"}), 400

    if pin != _pin:
        logger.warning(f"Pairing rejected for {device_name} ({device_id}): wrong PIN")
        return jsonify({"success": False, "error": "invalid PIN"}), 403

    token = generate_token()
    pairing.add_peer(device_id, device_name, token)
    logger.info(f"Paired new peer: {device_name} ({device_id})")
    return jsonify({"token": token}), 200


@app.route("/api/peers")
def api_peers():
    """List paired peers (tokens redacted)."""
    return jsonify({"peers": [
        {"peer_id": p["peer_id"], "name": p["name"]}
        for p in pairing.list_peers()
    ]})


@app.route("/api/status")
def api_status():
    """Receiver status endpoint."""
    return jsonify({
        "status": "online",
        "device_name": _device_name,
        "pin": _pin,
        "version": config.VERSION,
        "connected_senders": list(connected_senders),
        "latest_file": storage.latest_filename,
        "file_count": len(storage.list_files()),
        "local_ip": _get_local_ip(),
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Handle screenshot upload from sender."""
    token = request.headers.get("X-AirShare-Token", "")
    if not token or not pairing.is_valid_token(token):
        return jsonify({"success": False, "error": "not paired"}), 401
    try:
        # Check for image file
        if "image" not in request.files:
            return jsonify({"success": False, "error": "No image field in request"}), 400

        file = request.files["image"]
        if file.filename == "":
            return jsonify({"success": False, "error": "Empty filename"}), 400

        sender_name = request.form.get("sender_name", "Unknown")
        timestamp = request.form.get("timestamp", str(time.time()))

        # Read file data
        data = file.read()

        # Validate
        valid, error = storage.validate_file(data, file.filename)
        if not valid:
            return jsonify({"success": False, "error": error}), 400

        # Store
        metadata = storage.store_file(data, file.filename, sender_name)

        with _lock:
            connected_senders.add(sender_name)

        response = TransferResponse(
            success=True,
            filename=metadata["filename"],
            received_at=metadata["received_at"],
        )

        logger.info(f"Received screenshot from {sender_name}: {metadata['filename']}")
        return jsonify({
            "success": response.success,
            "filename": response.filename,
            "received_at": response.received_at,
        }), 200

    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/latest")
def api_latest():
    """Get latest received screenshot info."""
    if storage.latest_file:
        filename = os.path.basename(storage.latest_file)
        return jsonify({
            "filename": filename,
            "url": f"/received/{filename}",
            "exists": os.path.exists(storage.latest_file),
        })
    return jsonify({"filename": None, "url": None, "exists": False})


@app.route("/api/recent")
def api_recent():
    """Get recent transfers list."""
    return jsonify({"transfers": storage.get_recent_files(20)})


@app.route("/api/files")
def api_files():
    """List all received files."""
    return jsonify({"files": storage.list_files()})


@app.route("/received/<filename>")
def received_file(filename):
    """Serve a received file."""
    # Sanitize filename to prevent path traversal
    safe = os.path.basename(filename)
    return send_from_directory(storage.upload_dir, safe)


@app.route("/api/events")
def api_events():
    """Server-Sent Events endpoint for live updates."""
    def generate():
        last_file = None
        while True:
            current = storage.latest_filename
            if current and current != last_file:
                last_file = current
                yield f"data: {__import__('json').dumps({'event': 'new_transfer', 'filename': current})}\n\n"
            time.sleep(1)

    return app.response_class(generate(), mimetype="text/event-stream")


def start_receiver(host=None, port=None, device_name=None):
    """Start the receiver server."""
    global _device_name, _pin
    host = host or config.RECEIVER_HOST
    port = port or config.RECEIVER_PORT
    _device_name = device_name or "AirShare Receiver"
    _pin = generate_pin()

    logger.info(f"Starting AirShare Receiver on {host}:{port}")

    # Start UDP broadcaster
    broadcaster = DiscoveryBroadcaster(
        device_name=_device_name,
        port=port,
        host=_get_local_ip(),
    )
    broadcaster.start()

    # Start Flask
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    finally:
        broadcaster.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    start_receiver()
