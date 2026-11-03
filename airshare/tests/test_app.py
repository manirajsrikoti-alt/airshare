"""Tests for the unified airshare app, peer selection, and receiver-only fallback."""
import os
import sys
import json
import shutil
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from airshare.shared.protocol import ReceiverStatus


@pytest.fixture
def srv():
    """Flask test client with isolated pairing/target state."""
    from airshare.receiver import server as srv_mod
    from airshare.shared.pairing import PairingStore

    tmpdir = tempfile.mkdtemp()
    srv_mod.pairing = PairingStore(os.path.join(tmpdir, "peers.json"))
    srv_mod._pin = "123456"
    srv_mod.TARGET_FILE = os.path.join(tmpdir, "target.json")
    srv_mod._target_peer_id = None
    srv_mod._target_loaded = False
    srv_mod._peer_provider = None
    srv_mod._target_hook = None
    srv_mod._gesture_hook = None
    srv_mod._gestures_enabled = False
    srv_mod.app.config["TESTING"] = True
    yield srv_mod, srv_mod.app.test_client()
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestCLI:
    def test_help_exits_zero(self):
        from airshare.app import main
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_help_mentions_flags(self, capsys):
        from airshare.app import main
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        assert "--no-camera" in out
        assert "--port" in out
        assert "--device-name" in out


class TestPeersAPI:
    def test_peers_shape(self, srv):
        _, client = srv
        resp = client.get("/api/peers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data["peers"], list)
        assert "target" in data
        assert data["target"] is None

    def test_post_target_persists(self, srv):
        srv_mod, client = srv
        resp = client.post("/api/target", json={"peer_id": "192.168.1.5:5077"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        resp = client.get("/api/peers")
        assert resp.get_json()["target"] == "192.168.1.5:5077"

        # Persisted to disk, survives in-memory reset
        srv_mod._target_peer_id = None
        srv_mod._target_loaded = False
        resp = client.get("/api/peers")
        assert resp.get_json()["target"] == "192.168.1.5:5077"

    def test_post_target_requires_peer_id(self, srv):
        _, client = srv
        resp = client.post("/api/target", json={})
        assert resp.status_code == 400

    def test_discovered_peers_from_provider(self, srv):
        srv_mod, client = srv
        srv_mod._peer_provider = lambda: [
            {"peer_id": "10.0.0.2:5077", "name": "Laptop B", "host": "10.0.0.2", "port": 5077},
        ]
        data = client.get("/api/peers").get_json()
        assert data["peers"][0]["peer_id"] == "10.0.0.2:5077"
        assert data["peers"][0]["name"] == "Laptop B"


class TestGesturesAPI:
    def test_gestures_default_off(self, srv):
        _, client = srv
        data = client.get("/api/gestures").get_json()
        assert data["enabled"] is False

    def test_post_gestures_toggle(self, srv):
        srv_mod, client = srv
        calls = []
        srv_mod._gesture_hook = calls.append

        resp = client.post("/api/gestures", json={"enabled": True})
        assert resp.status_code == 200
        assert client.get("/api/gestures").get_json()["enabled"] is True
        assert calls == [True]

        client.post("/api/gestures", json={"enabled": False})
        assert client.get("/api/gestures").get_json()["enabled"] is False
        assert calls == [True, False]


class TestReceiverOnlyFallback:
    def test_camera_failure_yields_receiver_only(self):
        from airshare.app import AirShareApp
        with mock.patch("cv2.VideoCapture") as vc:
            vc.return_value.isOpened.return_value = False
            app = AirShareApp(no_camera=False)
            ok = app.start_sender()
        assert ok is False
        assert app.receiver_only is True
        assert app.sender is None

    def test_no_camera_flag_forces_receiver_only(self):
        from airshare.app import AirShareApp
        app = AirShareApp(no_camera=True)
        assert app.start_sender() is False
        assert app.receiver_only is True

    def test_camera_failure_logs_clear_message(self, caplog):
        from airshare.app import AirShareApp
        with mock.patch("cv2.VideoCapture") as vc:
            vc.return_value.isOpened.return_value = False
            app = AirShareApp(no_camera=False)
            with caplog.at_level("WARNING"):
                app.start_sender()
        assert any("receiver-only" in r.message.lower() for r in caplog.records)


class TestSetTarget:
    def test_set_target(self):
        from airshare.sender.network_client import NetworkClient
        nc = NetworkClient()
        peer = ReceiverStatus(device_name="Laptop B", host="10.0.0.2", port=5077)
        nc.set_target(peer)
        assert nc.is_connected is True
        assert nc.receiver is peer
        assert nc.receiver_name == "Laptop B"


class TestSenderGestures:
    def test_gestures_disabled_by_default(self):
        from airshare.sender.main import AirShareSender
        sender = AirShareSender()
        assert sender.gestures_enabled is False

    def test_set_gestures_enabled(self):
        from airshare.sender.main import AirShareSender
        sender = AirShareSender()
        sender.set_gestures_enabled(True)
        assert sender.gestures_enabled is True
        sender.set_gestures_enabled(False)
        assert sender.gestures_enabled is False
