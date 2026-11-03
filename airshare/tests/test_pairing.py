"""Tests for PIN pairing and per-peer token auth."""
import io
import os
import stat
import sys
import tempfile
import shutil
import time
from unittest import mock

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def make_test_image_bytes(width=64, height=64, color=(100, 150, 200)):
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPairingStore:
    """PairingStore persistence round-trip."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "peers.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_round_trip(self):
        from airshare.shared.pairing import PairingStore
        store = PairingStore(self.path)
        assert store.get_token("peer-1") is None

        store.add_peer("peer-1", "Laptop A", "token-abc")

        assert store.get_token("peer-1") == "token-abc"
        peers = store.list_peers()
        assert len(peers) == 1
        assert peers[0]["peer_id"] == "peer-1"
        assert peers[0]["name"] == "Laptop A"

        # Survives reload from disk
        store2 = PairingStore(self.path)
        assert store2.get_token("peer-1") == "token-abc"

    def test_file_permissions_600(self):
        from airshare.shared.pairing import PairingStore
        store = PairingStore(self.path)
        store.add_peer("peer-1", "Laptop A", "token-abc")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        assert mode == 0o600


class TestPairingAPI:
    """Pairing + token auth on the receiver Flask app."""

    def setup_method(self):
        from airshare.shared.pairing import PairingStore
        from airshare.receiver import server as srv_mod

        self.tmpdir = tempfile.mkdtemp()
        self.srv_mod = srv_mod
        srv_mod.app.config["TESTING"] = True

        # Isolate pairing state
        srv_mod.pairing = PairingStore(os.path.join(self.tmpdir, "peers.json"))
        srv_mod._pin = "123456"

        # Isolate storage
        upload_dir = os.path.join(self.tmpdir, "received")
        os.makedirs(upload_dir, exist_ok=True)
        srv_mod.storage.upload_dir = upload_dir
        srv_mod.storage._latest_file = None
        srv_mod.storage._transfer_log.clear()
        srv_mod.connected_senders.clear()

        self.client = srv_mod.app.test_client()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _pair(self, pin="123456"):
        return self.client.post("/api/pair", json={
            "pin": pin,
            "device_id": "test-device",
            "device_name": "Test Device",
        })

    def test_pair_wrong_pin_403(self):
        resp = self._pair(pin="000000")
        assert resp.status_code == 403

    def test_pair_correct_pin_returns_token(self):
        resp = self._pair()
        assert resp.status_code == 200
        token = resp.get_json()["token"]
        assert token
        # Token is stored for the peer
        assert self.srv_mod.pairing.get_token("test-device") == token

    def test_upload_without_token_401(self):
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(make_test_image_bytes()), "capture.png"),
                "sender_name": "Laptop A",
                "timestamp": str(time.time()),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"] == "not paired"

    def test_upload_invalid_token_401(self):
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(make_test_image_bytes()), "capture.png"),
                "sender_name": "Laptop A",
            },
            headers={"X-AirShare-Token": "bogus-token"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 401

    def test_upload_valid_token_200(self):
        token = self._pair().get_json()["token"]
        resp = self.client.post(
            "/api/upload",
            data={
                "image": (io.BytesIO(make_test_image_bytes()), "capture.png"),
                "sender_name": "Test Device",
                "timestamp": str(time.time()),
            },
            headers={"X-AirShare-Token": token},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


class TestNetworkClientPairing:
    """NetworkClient.pair and token header injection."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_client(self):
        from airshare.sender.network_client import NetworkClient
        from airshare.shared.pairing import PairingStore
        client = NetworkClient()
        client._pairing = PairingStore(os.path.join(self.tmpdir, "peers.json"))
        client._token = None
        return client

    def test_pair_success_stores_token(self):
        from airshare.sender.network_client import NetworkClient
        from airshare.shared.protocol import ReceiverStatus

        client = self._make_client()
        client._connected_receiver = ReceiverStatus(
            device_name="Test", host="127.0.0.1", port=5077,
        )

        with mock.patch("airshare.sender.network_client.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"token": "tok-123"}
            assert client.pair("123456") is True
            assert client._token == "tok-123"

    def test_pair_failure_returns_false(self):
        from airshare.sender.network_client import NetworkClient
        from airshare.shared.protocol import ReceiverStatus

        client = self._make_client()
        client._connected_receiver = ReceiverStatus(
            device_name="Test", host="127.0.0.1", port=5077,
        )

        with mock.patch("airshare.sender.network_client.requests.post") as post:
            post.return_value.status_code = 403
            assert client.pair("000000") is False
            assert client._token is None

    def test_upload_sends_token_header(self):
        from airshare.sender.network_client import NetworkClient
        from airshare.shared.protocol import ReceiverStatus

        client = self._make_client()
        client._connected_receiver = ReceiverStatus(
            device_name="Test", host="127.0.0.1", port=5077,
        )
        client._token = "tok-123"

        with mock.patch("airshare.sender.network_client.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {
                "success": True, "filename": "f.png", "received_at": "now",
            }
            client.upload_screenshot(b"\x89PNG", "capture.png")

        _, kwargs = post.call_args
        assert kwargs["headers"]["X-AirShare-Token"] == "tok-123"
