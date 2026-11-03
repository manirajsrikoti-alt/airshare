"""Integration tests for the full AirShare end-to-end flow.

Tests the receiver server, file upload, discovery, and network client
without requiring a physical webcam.
"""
import io
import os
import sys
import time
import threading
import tempfile
import shutil
import pytest
import requests
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from airshare import config
from airshare.receiver.storage import StorageManager
from airshare.shared.protocol import TransferRequest, TransferResponse, ReceiverStatus
from airshare.shared.models import SenderState, GestureType


def make_test_image_bytes(width=1920, height=1080, color=(100, 150, 200)):
    """Create a realistic-size test PNG image."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def pair_and_get_headers(client):
    """Pair a test device with the receiver and return auth headers."""
    resp = client.post("/api/pair", json={
        "pin": "123456",
        "device_id": "integration-test-device",
        "device_name": "Integration Test",
    })
    assert resp.status_code == 200
    return {"X-AirShare-Token": resp.get_json()["token"]}


def isolate_pairing(srv_mod, tmpdir):
    """Point the server's pairing store at a temp file with a known PIN."""
    from airshare.shared.pairing import PairingStore
    srv_mod.pairing = PairingStore(os.path.join(tmpdir, "peers.json"))
    srv_mod._pin = "123456"


class TestEndToEndFlow:
    """Full end-to-end flow tests using the real Flask test client."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.mkdtemp()
        self.upload_dir = os.path.join(self.tmpdir, "received")
        os.makedirs(self.upload_dir, exist_ok=True)
        self.screenshot_dir = os.path.join(self.tmpdir, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)

        # Import and configure Flask app
        from airshare.receiver.server import app, storage
        self.app = app
        self.app.config["TESTING"] = True

        # Override storage to use temp directory and reset state
        storage.upload_dir = self.upload_dir
        storage._latest_file = None
        storage._transfer_log.clear()

        # Reset connected senders
        from airshare.receiver import server as srv_mod
        srv_mod.connected_senders.clear()

        # Isolate pairing state and pair a test device
        isolate_pairing(srv_mod, self.tmpdir)

        self.client = self.app.test_client()
        self.storage = storage
        self.headers = pair_and_get_headers(self.client)

        # Inject the auth header into every /api/upload call
        original_post = self.client.post
        def _authed_post(path, *args, **kwargs):
            if path == "/api/upload":
                headers = dict(kwargs.get("headers") or {})
                headers.update(self.headers)
                kwargs["headers"] = headers
            return original_post(path, *args, **kwargs)
        self.client.post = _authed_post

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- Receiver API Tests ----

    def test_receiver_status_endpoint(self):
        """GET /api/status returns online status."""
        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "online"
        assert "device_name" in data
        assert "version" in data
        assert "local_ip" in data

    def test_receiver_dashboard(self):
        """GET / renders the dashboard HTML."""
        resp = self.client.get("/")
        assert resp.status_code == 200
        assert b"AirShare" in resp.data

    def test_upload_valid_screenshot(self):
        """POST /api/upload with a valid PNG image succeeds."""
        img_data = make_test_image_bytes()
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(img_data), "capture_20260831_105532.png"),
                "sender_name": "Laptop A",
                "timestamp": str(time.time()),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "filename" in data
        assert data["filename"].startswith("airshare_")
        assert data["received_at"] != ""

    def test_upload_missing_image_field(self):
        """POST /api/upload without image field returns 400."""
        resp = self.client.post(
            "/api/upload",
            data={"sender_name": "Laptop A"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "No image" in data["error"]

    def test_upload_empty_filename(self):
        """POST /api/upload with empty filename returns 400."""
        img_data = make_test_image_bytes()
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(img_data), ""),
                "sender_name": "Laptop A",
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_upload_invalid_file_type(self):
        """POST /api/upload with .exe extension is rejected."""
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(b"not really exe"), "malware.exe"),
                "sender_name": "Laptop A",
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_upload_corrupt_image_data(self):
        """POST /api/upload with corrupt image data is rejected."""
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(b"this is not an image"), "fake.png"),
                "sender_name": "Laptop A",
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "invalid" in data["error"].lower() or "Invalid" in data["error"]

    def test_upload_oversized_file(self):
        """POST /api/upload with oversized file is rejected."""
        oversized = b"x" * (config.MAX_UPLOAD_SIZE + 1)
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(oversized), "huge.png"),
                "sender_name": "Laptop A",
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "too large" in data["error"].lower()

    def test_latest_endpoint_after_upload(self):
        """GET /api/latest returns the most recent upload."""
        img_data = make_test_image_bytes()
        self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(img_data), "capture.png"),
                "sender_name": "Laptop A",
            },
            content_type="multipart/form-data",
        )
        resp = self.client.get("/api/latest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["filename"] is not None
        assert data["exists"] is True

    def test_latest_endpoint_no_uploads(self):
        """GET /api/latest returns null when nothing uploaded."""
        resp = self.client.get("/api/latest")
        data = resp.get_json()
        assert data["filename"] is None

    def test_recent_transfers(self):
        """GET /api/recent returns upload history."""
        img_data = make_test_image_bytes()
        for i in range(3):
            self.client.post(
                "/api/upload",
                data={
                    "image": (io.BytesIO(img_data), f"capture_{i}.png"),
                    "sender_name": f"Sender {i}",
                },
                content_type="multipart/form-data",
            )
        resp = self.client.get("/api/recent")
        data = resp.get_json()
        assert len(data["transfers"]) == 3
        # Most recent first
        assert data["transfers"][0]["sender"] == "Sender 2"

    def test_files_list(self):
        """GET /api/files lists stored files."""
        img_data = make_test_image_bytes()
        self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(img_data), "capture.png"),
                "sender_name": "Test",
            },
            content_type="multipart/form-data",
        )
        resp = self.client.get("/api/files")
        data = resp.get_json()
        assert len(data["files"]) >= 1

    def test_serve_received_file(self):
        """GET /received/<filename> serves the uploaded file."""
        img_data = make_test_image_bytes()
        upload_resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(img_data), "capture.png"),
                "sender_name": "Test",
            },
            content_type="multipart/form-data",
        )
        filename = upload_resp.get_json()["filename"]
        resp = self.client.get(f"/received/{filename}")
        assert resp.status_code == 200
        assert len(resp.data) > 0
        # Verify it's valid PNG
        img = Image.open(io.BytesIO(resp.data))
        assert img.size == (1920, 1080)

    def test_serve_nonexistent_file(self):
        """GET /received/nonexistent.png returns 404."""
        resp = self.client.get("/received/nonexistent.png")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self):
        """GET /received/../../etc/passwd is blocked."""
        resp = self.client.get("/received/../../etc/passwd")
        assert resp.status_code in (404, 400)


class TestFullTransferFlow:
    """Simulate the full capture → transfer → receive flow."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.upload_dir = os.path.join(self.tmpdir, "received")
        os.makedirs(self.upload_dir, exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_capture_and_transfer_flow(self):
        """Simulate: capture screenshot → upload → verify on receiver."""
        from airshare.receiver.server import app, storage

        storage.upload_dir = self.upload_dir
        storage._latest_file = None
        storage._transfer_log.clear()
        app.config["TESTING"] = True
        client = app.test_client()

        from airshare.receiver import server as srv_mod
        isolate_pairing(srv_mod, self.tmpdir)
        headers = pair_and_get_headers(client)

        # Step 1: Simulate screenshot capture (create a test image file)
        screenshot_path = os.path.join(self.tmpdir, "capture_test.png")
        img = Image.new("RGB", (1920, 1080), (50, 100, 200))
        img.save(screenshot_path, "PNG")

        # Step 2: Read the "captured" screenshot
        with open(screenshot_path, "rb") as f:
            file_data = f.read()

        assert len(file_data) > 0

        # Step 3: Upload to receiver (simulating network_client.upload_screenshot)
        resp = client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(file_data), "capture_test.png"),
                "sender_name": "Laptop A",
                "timestamp": str(time.time()),
            },
            headers=headers,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["success"] is True

        # Step 4: Verify the file is retrievable
        resp = client.get(f"/received/{result['filename']}")
        assert resp.status_code == 200
        received_img = Image.open(io.BytesIO(resp.data))
        assert received_img.size == (1920, 1080)

        # Step 5: Verify it appears in latest
        resp = client.get("/api/latest")
        latest = resp.get_json()
        assert latest["filename"] == result["filename"]
        assert latest["exists"] is True

        # Step 6: Verify it's in the recent list
        resp = client.get("/api/recent")
        recent = resp.get_json()
        assert any(t["filename"] == result["filename"] for t in recent["transfers"])

        # Step 7: Dashboard shows the transfer
        resp = client.get("/")
        assert resp.status_code == 200

    def test_multiple_transfers_sequential(self):
        """Multiple screenshots transferred in sequence."""
        from airshare.receiver.server import app, storage
        from airshare.receiver import server as srv_mod

        storage.upload_dir = self.upload_dir
        storage._latest_file = None
        storage._transfer_log.clear()
        srv_mod.connected_senders.clear()
        app.config["TESTING"] = True
        client = app.test_client()
        isolate_pairing(srv_mod, self.tmpdir)
        headers = pair_and_get_headers(client)

        filenames = []
        for i in range(5):
            img = Image.new("RGB", (800, 600), (i * 50, 100, 200 - i * 30))
            buf = io.BytesIO()
            img.save(buf, format="PNG")

            resp = client.post(
                "/api/upload",
                data={
                    "image": (io.BytesIO(buf.getvalue()), f"capture_{i}.png"),
                    "sender_name": "Laptop A",
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            if resp.status_code != 200:
                print(f"Upload {i} failed: {resp.status_code} {resp.get_json()}")
            assert resp.status_code == 200
            filenames.append(resp.get_json()["filename"])

        # All 5 should be stored
        resp = client.get("/api/files")
        files = resp.get_json()["files"]
        assert len(files) == 5

        # Latest should be the last one
        resp = client.get("/api/latest")
        assert resp.get_json()["filename"] == filenames[-1]

        # All should be retrievable
        for fn in filenames:
            resp = client.get(f"/received/{fn}")
            assert resp.status_code == 200


class TestStateTransitions:
    """Test the complete state machine flow for the full interaction."""

    def test_full_interaction_flow(self):
        """Simulate the complete user interaction flow through states."""
        from airshare.sender.gesture_state import GestureStateMachine
        from airshare.shared.models import SenderState

        sm = GestureStateMachine()

        # Boot sequence
        sm.force_state(SenderState.READY)
        assert sm.ready_for_new_action()

        # User performs upward push → capture detected
        sm.transition(SenderState.CAPTURE_DETECTED)
        sm.transition(SenderState.CAPTURING)
        sm.transition(SenderState.CAPTURED)
        sm.transition(SenderState.READY_TO_TRANSFER)

        # Ready to transfer
        assert sm.state == SenderState.READY_TO_TRANSFER

        # User throws outward → transfer
        sm.transition(SenderState.TRANSFER_DETECTED)
        sm.transition(SenderState.SENDING)
        sm.transition(SenderState.TRANSFER_SUCCESS)

        # Back to ready for next gesture
        sm.transition(SenderState.READY)
        assert sm.state == SenderState.READY
        assert sm.ready_for_new_action()

    def test_failed_transfer_recovery(self):
        """Transfer failure allows retry."""
        from airshare.sender.gesture_state import GestureStateMachine
        from airshare.shared.models import SenderState

        sm = GestureStateMachine()
        sm.force_state(SenderState.READY)

        # Capture
        sm.transition(SenderState.CAPTURE_DETECTED)
        sm.transition(SenderState.CAPTURING)
        sm.transition(SenderState.CAPTURED)
        sm.transition(SenderState.READY_TO_TRANSFER)

        # Transfer fails
        sm.transition(SenderState.TRANSFER_DETECTED)
        sm.transition(SenderState.TRANSFER_FAILED)

        # Can retry from READY_TO_TRANSFER
        sm.transition(SenderState.READY_TO_TRANSFER)
        assert sm.state == SenderState.READY_TO_TRANSFER

        # Second attempt succeeds
        sm.transition(SenderState.TRANSFER_DETECTED)
        sm.transition(SenderState.SENDING)
        sm.transition(SenderState.TRANSFER_SUCCESS)
        sm.transition(SenderState.READY)
        assert sm.state == SenderState.READY
