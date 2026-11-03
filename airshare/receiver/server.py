"""Flask-based receiver server for AirShare."""
import os
import hmac
import json
import functools
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

# --- Unified-app runtime hooks (wired by airshare.app) ---
_peer_provider = None    # callable() -> list[dict] of discovered receiver peers
_target_hook = None      # callable(peer_id) -> bool: True when the target was applied
_gesture_hook = None     # callable(enabled: bool) toggles sender gesture tracking
_pair_hook = None        # callable(peer_id, pin) -> bool: pair the sender with a peer
_gestures_enabled = False

# --- Loopback gating + pairing rate limit ---
PAIR_MAX_FAILURES = 5        # failed PIN attempts allowed per window per client
PAIR_FAILURE_WINDOW = 60     # seconds
_pair_failures = {}          # remote_addr -> [failure timestamps]
_pair_lock = threading.Lock()


def _is_loopback(addr) -> bool:
    """True when the request originates from this machine."""
    return bool(addr) and (addr == "::1" or addr.startswith("127."))


def _loopback_only(view):
    """Restrict a dashboard control endpoint to requests from this machine."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not _is_loopback(request.remote_addr):
            logger.warning(
                f"Blocked remote access to {request.path} from {request.remote_addr}"
            )
            return jsonify({"success": False, "error": "local access only"}), 403
        return view(*args, **kwargs)
    return wrapper


def _pair_rate_limited(addr) -> bool:
    with _pair_lock:
        now = time.time()
        fails = [t for t in _pair_failures.get(addr, []) if now - t < PAIR_FAILURE_WINDOW]
        _pair_failures[addr] = fails
        return len(fails) >= PAIR_MAX_FAILURES


def _record_pair_failure(addr):
    with _pair_lock:
        _pair_failures.setdefault(addr, []).append(time.time())


def _clear_pair_failures(addr):
    with _pair_lock:
        _pair_failures.pop(addr, None)

TARGET_FILE = os.path.join(os.path.expanduser("~"), ".airshare", "target.json")
_target_peer_id = None
_target_loaded = False
_app_mode = "receiver"


def set_mode(mode: str):
    """Record the app mode ('full' or 'receiver-only') for the dashboard."""
    global _app_mode
    _app_mode = mode


def configure_runtime(peer_provider=None, target_hook=None, gesture_hook=None,
                      pair_hook=None):
    """Wire unified-app hooks for peer listing, target selection, gestures, pairing."""
    global _peer_provider, _target_hook, _gesture_hook, _pair_hook
    _peer_provider = peer_provider
    _target_hook = target_hook
    _gesture_hook = gesture_hook
    _pair_hook = pair_hook


def get_pin() -> str:
    """The current pairing PIN (local use only — never serve to LAN clients)."""
    return _pin


def print_pin():
    """Print the pairing PIN to the terminal so headless users can see it."""
    msg = f"AirShare pairing PIN: {_pin} (enter it on the sending machine's dashboard)"
    print(msg, flush=True)
    logger.info(msg)


def get_target():
    """Return the persisted target peer_id, or None."""
    global _target_peer_id, _target_loaded
    if not _target_loaded:
        _target_loaded = True
        try:
            with open(TARGET_FILE, "r", encoding="utf-8") as f:
                _target_peer_id = json.load(f).get("target")
        except (OSError, ValueError):
            _target_peer_id = None
    return _target_peer_id


def set_target(peer_id):
    """Persist the selected target peer_id."""
    global _target_peer_id, _target_loaded
    _target_peer_id = peer_id
    _target_loaded = True
    os.makedirs(os.path.dirname(TARGET_FILE), exist_ok=True)
    tmp = TARGET_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"target": peer_id}, f)
    os.replace(tmp, TARGET_FILE)


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
    """Dashboard page. The pairing PIN is only rendered for loopback clients —
    a LAN snooper browsing the dashboard must not see it."""
    pin = _pin if _is_loopback(request.remote_addr) else None
    return render_template("index.html", device_name=_device_name, pin=pin)


@app.route("/api/pair", methods=["POST"])
def api_pair():
    """Pair a sender using the dashboard PIN and issue a per-peer token."""
    addr = request.remote_addr or ""
    if _pair_rate_limited(addr):
        logger.warning(f"Pairing rate-limited for {addr}: too many failed attempts")
        return jsonify({"success": False, "error": "too many attempts"}), 429

    data = request.get_json(silent=True) or {}
    pin = data.get("pin", "")
    device_id = data.get("device_id", "")
    device_name = data.get("device_name", "Unknown")

    if not pin or not device_id:
        return jsonify({"success": False, "error": "pin and device_id required"}), 400

    if not hmac.compare_digest(str(pin), str(_pin)):
        _record_pair_failure(addr)
        logger.warning(f"Pairing rejected for {device_name} ({device_id}): wrong PIN")
        return jsonify({"success": False, "error": "invalid PIN"}), 403

    _clear_pair_failures(addr)
    token = generate_token()
    pairing.add_peer(device_id, device_name, token)
    logger.info(f"Paired new peer: {device_name} ({device_id})")
    return jsonify({"token": token}), 200


@app.route("/api/peers")
def api_peers():
    """List discovered + paired peers and the current upload target."""
    paired = {p["peer_id"]: p["name"] for p in pairing.list_peers()}

    discovered = []
    if _peer_provider:
        try:
            discovered = _peer_provider() or []
        except Exception as e:
            logger.error(f"Peer provider error: {e}")

    peers = []
    seen = set()
    for d in discovered:
        pid = d.get("peer_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        peers.append({
            "peer_id": pid,
            "name": d.get("name", pid),
            "host": d.get("host", ""),
            "port": d.get("port"),
            # Sender-side pairing (we hold a token for them) wins when reported
            "paired": bool(d.get("paired", pid in paired)),
        })
    for pid, name in paired.items():
        if pid not in seen:
            peers.append({"peer_id": pid, "name": name, "host": "", "port": None, "paired": True})

    return jsonify({"peers": peers, "target": get_target()})


@app.route("/api/target", methods=["POST"])
@_loopback_only
def api_target():
    """Select the default upload target peer (local dashboard control)."""
    data = request.get_json(silent=True) or {}
    peer_id = data.get("peer_id")
    if not peer_id:
        return jsonify({"success": False, "error": "peer_id required"}), 400

    if _target_hook:
        try:
            if _target_hook(peer_id) is False:
                return jsonify({
                    "success": False,
                    "error": "unknown peer (must be discovered or paired)",
                }), 400
        except Exception as e:
            logger.error(f"Target hook error: {e}")
            return jsonify({"success": False, "error": "target could not be applied"}), 500
    set_target(peer_id)
    logger.info(f"Upload target selected: {peer_id}")
    return jsonify({"success": True, "target": peer_id}), 200


@app.route("/api/gestures", methods=["GET", "POST"])
@_loopback_only
def api_gestures():
    """Get or toggle webcam gesture tracking (OFF by default, local control)."""
    global _gestures_enabled
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            return jsonify({"success": False, "error": "boolean 'enabled' required"}), 400
        _gestures_enabled = enabled
        if _gesture_hook:
            try:
                _gesture_hook(_gestures_enabled)
            except Exception as e:
                logger.error(f"Gesture hook error: {e}")
        logger.info(f"Gesture tracking {'enabled' if _gestures_enabled else 'disabled'} via dashboard")
    return jsonify({"enabled": _gestures_enabled})


@app.route("/api/pair-peer", methods=["POST"])
@_loopback_only
def api_pair_peer():
    """Pair this machine's sender with a discovered peer using its PIN.

    Local dashboard control: the dashboard user enters the PIN shown on the
    *other* machine; the app-level hook connects and performs the pairing,
    storing the issued token in the sender's PairingStore."""
    if not _pair_hook:
        return jsonify({"success": False, "error": "pairing unavailable (no sender)"}), 503

    data = request.get_json(silent=True) or {}
    peer_id = data.get("peer_id")
    pin = data.get("pin")
    if not peer_id or not pin:
        return jsonify({"success": False, "error": "peer_id and pin required"}), 400

    try:
        ok = bool(_pair_hook(peer_id, pin))
    except Exception as e:
        logger.error(f"Pair hook error: {e}")
        return jsonify({"success": False, "error": "pairing failed"}), 500

    if not ok:
        return jsonify({"success": False, "error": "pairing failed (wrong PIN or peer unreachable)"}), 403
    logger.info(f"Paired with peer {peer_id} via dashboard")
    return jsonify({"success": True, "peer_id": peer_id}), 200


@app.route("/api/status")
def api_status():
    """Receiver status endpoint."""
    return jsonify({
        "status": "online",
        "device_name": _device_name,
        "mode": _app_mode,
        "gestures_enabled": _gestures_enabled,
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
        return jsonify({"success": False, "error": "internal upload error"}), 500


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
    print_pin()

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
