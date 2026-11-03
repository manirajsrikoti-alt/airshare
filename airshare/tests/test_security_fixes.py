"""Tests for the v1.0 final-review security fixes:
loopback gating, PIN privacy, pair rate limiting, pair-peer endpoint,
per-receiver token keying, and data-dir locations."""
import io
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

REMOTE = {"REMOTE_ADDR": "192.168.1.50"}
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}


def make_test_image_bytes(width=64, height=64, color=(100, 150, 200)):
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def srv():
    """Flask test client with fully isolated server state."""
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
    srv_mod._pair_hook = None
    srv_mod._gestures_enabled = False
    with srv_mod._pair_lock:
        srv_mod._pair_failures.clear()
    upload_dir = os.path.join(tmpdir, "received")
    os.makedirs(upload_dir, exist_ok=True)
    srv_mod.storage.upload_dir = upload_dir
    srv_mod.storage._latest_file = None
    srv_mod.storage._transfer_log.clear()
    srv_mod.connected_senders.clear()
    srv_mod.app.config["TESTING"] = True
    yield srv_mod, srv_mod.app.test_client()
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestPinPrivacy:
    def test_loopback_dashboard_shows_pin(self, srv):
        _, client = srv
        resp = client.get("/", environ_overrides=LOOPBACK)
        assert resp.status_code == 200
        assert "123456" in resp.get_data(as_text=True)

    def test_remote_dashboard_hides_pin(self, srv):
        _, client = srv
        resp = client.get("/", environ_overrides=REMOTE)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "123456" not in html

    def test_pin_printed_on_receiver_startup(self, capsys):
        from airshare.receiver import server as srv_mod
        srv_mod._pin = "654321"
        srv_mod.print_pin()
        out = capsys.readouterr().out
        assert "654321" in out


class TestLoopbackGating:
    def test_remote_target_post_403(self, srv):
        _, client = srv
        resp = client.post("/api/target", json={"peer_id": "10.0.0.2:5077"},
                           environ_overrides=REMOTE)
        assert resp.status_code == 403

    def test_loopback_target_post_works(self, srv):
        _, client = srv
        resp = client.post("/api/target", json={"peer_id": "10.0.0.2:5077"},
                           environ_overrides=LOOPBACK)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_remote_gestures_post_403(self, srv):
        _, client = srv
        resp = client.post("/api/gestures", json={"enabled": True},
                           environ_overrides=REMOTE)
        assert resp.status_code == 403
        assert client.get("/api/gestures").get_json()["enabled"] is False

    def test_remote_pair_peer_403(self, srv):
        srv_mod, client = srv
        srv_mod._pair_hook = lambda peer_id, pin: True
        resp = client.post("/api/pair-peer",
                           json={"peer_id": "10.0.0.2:5077", "pin": "123456"},
                           environ_overrides=REMOTE)
        assert resp.status_code == 403


class TestGesturesValidation:
    def test_missing_enabled_400(self, srv):
        _, client = srv
        resp = client.post("/api/gestures", json={}, environ_overrides=LOOPBACK)
        assert resp.status_code == 400

    def test_non_bool_enabled_400(self, srv):
        _, client = srv
        resp = client.post("/api/gestures", json={"enabled": "yes"},
                           environ_overrides=LOOPBACK)
        assert resp.status_code == 400


class TestPairPeerEndpoint:
    def test_success(self, srv):
        srv_mod, client = srv
        calls = []
        srv_mod._pair_hook = lambda peer_id, pin: calls.append((peer_id, pin)) or True
        resp = client.post("/api/pair-peer",
                           json={"peer_id": "10.0.0.2:5077", "pin": "123456"},
                           environ_overrides=LOOPBACK)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert calls == [("10.0.0.2:5077", "123456")]

    def test_failure_403(self, srv):
        srv_mod, client = srv
        srv_mod._pair_hook = lambda peer_id, pin: False
        resp = client.post("/api/pair-peer",
                           json={"peer_id": "10.0.0.2:5077", "pin": "000000"},
                           environ_overrides=LOOPBACK)
        assert resp.status_code == 403
        assert resp.get_json()["success"] is False

    def test_missing_fields_400(self, srv):
        srv_mod, client = srv
        srv_mod._pair_hook = lambda peer_id, pin: True
        resp = client.post("/api/pair-peer", json={"peer_id": "10.0.0.2:5077"},
                           environ_overrides=LOOPBACK)
        assert resp.status_code == 400

    def test_no_hook_503(self, srv):
        _, client = srv
        resp = client.post("/api/pair-peer",
                           json={"peer_id": "10.0.0.2:5077", "pin": "123456"},
                           environ_overrides=LOOPBACK)
        assert resp.status_code == 503


class TestPairRateLimit:
    def _pair(self, client, pin):
        return client.post("/api/pair", json={
            "pin": pin, "device_id": "dev-1", "device_name": "Test",
        }, environ_overrides=REMOTE)

    def test_five_failures_then_429(self, srv):
        srv_mod, client = srv
        for _ in range(srv_mod.PAIR_MAX_FAILURES):
            assert self._pair(client, "000000").status_code == 403
        # Sixth attempt within the window is throttled — even with the right PIN
        assert self._pair(client, "000000").status_code == 429
        assert self._pair(client, "123456").status_code == 429

    def test_limit_is_per_remote_addr(self, srv):
        srv_mod, client = srv
        for _ in range(srv_mod.PAIR_MAX_FAILURES):
            self._pair(client, "000000")
        # A different client address is not throttled
        resp = client.post("/api/pair", json={
            "pin": "123456", "device_id": "dev-2", "device_name": "Other",
        }, environ_overrides={"REMOTE_ADDR": "192.168.1.99"})
        assert resp.status_code == 200

    def test_success_clears_failures(self, srv):
        srv_mod, client = srv
        for _ in range(srv_mod.PAIR_MAX_FAILURES - 1):
            self._pair(client, "000000")
        assert self._pair(client, "123456").status_code == 200
        # Counter reset: more failures allowed before throttling
        for _ in range(srv_mod.PAIR_MAX_FAILURES - 1):
            assert self._pair(client, "000000").status_code == 403


class TestTargetValidation:
    def test_hook_rejects_unknown_peer(self, srv):
        srv_mod, client = srv
        srv_mod._target_hook = lambda peer_id: False
        resp = client.post("/api/target", json={"peer_id": "6.6.6.6:5077"},
                           environ_overrides=LOOPBACK)
        assert resp.status_code == 400
        assert srv_mod.get_target() is None


class TestApplyTargetPolicy:
    """AirShareApp.apply_target only accepts discovered or paired peers."""

    def _app_with_sender(self):
        from airshare.app import AirShareApp
        from airshare.shared.pairing import PairingStore
        tmpdir = tempfile.mkdtemp()
        app = AirShareApp(no_camera=True)
        sender = mock.Mock()
        sender.network._pairing = PairingStore(os.path.join(tmpdir, "peers.json"))
        app.sender = sender
        return app, tmpdir

    def test_rejects_arbitrary_host_port(self):
        from airshare.shared.protocol import ReceiverStatus
        app, tmpdir = self._app_with_sender()
        try:
            app.sender.network.get_discovered_receivers.return_value = []
            assert app.apply_target("6.6.6.6:5077") is False
            app.sender.network.set_target.assert_not_called()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_accepts_discovered_peer(self):
        from airshare.shared.protocol import ReceiverStatus
        app, tmpdir = self._app_with_sender()
        try:
            peer = ReceiverStatus(device_name="B", host="10.0.0.2", port=5077)
            app.sender.network.get_discovered_receivers.return_value = [peer]
            assert app.apply_target("10.0.0.2:5077") is True
            app.sender.network.set_target.assert_called_once_with(peer)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_accepts_paired_peer(self):
        app, tmpdir = self._app_with_sender()
        try:
            app.sender.network.get_discovered_receivers.return_value = []
            app.sender.network._pairing.add_peer("10.0.0.9:5077", "Old", "tok")
            assert app.apply_target("10.0.0.9:5077") is True
            target = app.sender.network.set_target.call_args[0][0]
            assert (target.host, target.port) == ("10.0.0.9", 5077)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestPeerListSelfFilter:
    def test_own_broadcast_filtered(self):
        from airshare.app import AirShareApp, _get_local_ip
        from airshare.shared.protocol import ReceiverStatus
        app = AirShareApp(no_camera=True, port=5077)
        sender = mock.Mock()
        own = ReceiverStatus(device_name="me", host=_get_local_ip(), port=5077)
        loop = ReceiverStatus(device_name="me-loop", host="127.0.0.1", port=5077)
        other = ReceiverStatus(device_name="B", host="10.0.0.2", port=5077)
        same_host_other_port = ReceiverStatus(device_name="alt", host=_get_local_ip(), port=5099)
        sender.network.get_discovered_receivers.return_value = [own, loop, other, same_host_other_port]
        app.sender = sender
        peers = app.peer_list()
        ids = [p["peer_id"] for p in peers]
        assert ids == ["10.0.0.2:5077", f"{_get_local_ip()}:5099"]


class TestPairWithPeer:
    def test_unknown_peer_false(self):
        from airshare.app import AirShareApp
        app = AirShareApp(no_camera=True)
        sender = mock.Mock()
        sender.network.get_discovered_receivers.return_value = []
        app.sender = sender
        assert app.pair_with_peer("10.0.0.2:5077", "123456") is False

    def test_connect_and_pair(self):
        from airshare.app import AirShareApp
        from airshare.shared.protocol import ReceiverStatus
        app = AirShareApp(no_camera=True)
        peer = ReceiverStatus(device_name="B", host="10.0.0.2", port=5077)
        sender = mock.Mock()
        sender.network.get_discovered_receivers.return_value = [peer]
        sender.network.connect_to_receiver.return_value = True
        sender.network.pair.return_value = True
        app.sender = sender
        assert app.pair_with_peer("10.0.0.2:5077", "123456") is True
        sender.network.connect_to_receiver.assert_called_once_with(peer)
        sender.network.pair.assert_called_once_with("123456")


class TestSenderTokenKeying:
    """Sender-side tokens are keyed by the target receiver's host:port."""

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

    def test_pair_stores_token_by_host_port(self):
        from airshare.shared.protocol import ReceiverStatus
        client = self._make_client()
        client._connected_receiver = ReceiverStatus(
            device_name="Test", host="10.0.0.2", port=5077,
        )
        with mock.patch("airshare.sender.network_client.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"token": "tok-aaa"}
            assert client.pair("123456") is True
        assert client._pairing.get_token("10.0.0.2:5077") == "tok-aaa"
        assert client._token == "tok-aaa"

    def test_multiple_receivers_keep_separate_tokens(self):
        from airshare.shared.protocol import ReceiverStatus
        client = self._make_client()
        client._pairing.add_peer("10.0.0.2:5077", "B", "tok-b")
        client._pairing.add_peer("10.0.0.3:5077", "C", "tok-c")

        client.set_target(ReceiverStatus(device_name="B", host="10.0.0.2", port=5077))
        assert client._token == "tok-b"
        client.set_target(ReceiverStatus(device_name="C", host="10.0.0.3", port=5077))
        assert client._token == "tok-c"
        client.set_target(ReceiverStatus(device_name="X", host="10.0.0.4", port=5077))
        assert client._token is None

    def test_upload_uses_current_receivers_token(self):
        from airshare.shared.protocol import ReceiverStatus
        client = self._make_client()
        client._pairing.add_peer("10.0.0.2:5077", "B", "tok-b")
        client.set_target(ReceiverStatus(device_name="B", host="10.0.0.2", port=5077))

        with mock.patch("airshare.sender.network_client.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {
                "success": True, "filename": "f.png", "received_at": "now",
            }
            client.upload_screenshot(b"\x89PNG", "capture.png")
        _, kwargs = post.call_args
        assert kwargs["headers"]["X-AirShare-Token"] == "tok-b"


class TestDataDirs:
    def test_dirs_under_home_not_package(self):
        from airshare import config
        home = os.path.expanduser("~")
        assert config.RECEIVER_UPLOAD_DIR == os.path.join(home, ".airshare", "received")
        assert config.SCREENSHOT_DIR == os.path.join(home, ".airshare", "screenshots")
        pkg_dir = os.path.dirname(config.__file__)
        assert not config.RECEIVER_UPLOAD_DIR.startswith(pkg_dir)
        assert not config.SCREENSHOT_DIR.startswith(pkg_dir)

    def test_dead_config_keys_removed(self):
        from airshare import config
        assert not hasattr(config, "THUMB_DWELL_MS")
        assert not hasattr(config, "THUMB_CORNER_RADIUS_PCT")


class TestUploadErrorMessage:
    def test_500_does_not_leak_exception(self, srv):
        srv_mod, client = srv
        token = client.post("/api/pair", json={
            "pin": "123456", "device_id": "dev-1", "device_name": "Test",
        }).get_json()["token"]
        with mock.patch.object(srv_mod.storage, "store_file",
                               side_effect=RuntimeError("secret /etc/passwd path")):
            resp = client.post(
                "/api/upload",
                data={"image": (io.BytesIO(make_test_image_bytes()), "capture.png"),
                      "sender_name": "Test"},
                headers={"X-AirShare-Token": token},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 500
        body = resp.get_data(as_text=True)
        assert "secret" not in body
        assert resp.get_json()["error"] == "internal upload error"


class TestCalibrationData:
    def test_dead_fields_removed(self):
        from airshare.shared.models import CalibrationData
        cal = CalibrationData(sample_count=3, timestamp=time.time())
        assert not hasattr(cal, "capture_avg_displacement")
        assert not hasattr(cal, "transfer_direction_ratio")
        assert cal.sample_count == 3
