"""Tests for reliability: stale peer filtering, upload retry, reconnect."""
import time

import pytest
import requests

from airshare import config
from airshare.receiver.discovery import DiscoveryListener
from airshare.sender.network_client import NetworkClient
from airshare.shared.protocol import ReceiverStatus


def _make_client() -> NetworkClient:
    """NetworkClient without starting any listener threads."""
    return NetworkClient()


class TestStalePeerFiltering:
    def test_stale_receiver_is_filtered_out(self):
        listener = DiscoveryListener()
        fresh = ReceiverStatus(device_name="Fresh", host="10.0.0.1", port=5077)
        stale = ReceiverStatus(device_name="Stale", host="10.0.0.2", port=5077)
        stale.last_seen = time.time() - config.PEER_STALE_TIMEOUT - 1
        listener._receivers["10.0.0.1:5077"] = fresh
        listener._receivers["10.0.0.2:5077"] = stale

        names = [r.device_name for r in listener.receivers]
        assert "Fresh" in names
        assert "Stale" not in names

    def test_receivers_property_does_not_crash_on_string_host(self):
        listener = DiscoveryListener()
        listener._receivers["10.0.0.3:5077"] = ReceiverStatus(
            device_name="B", host="10.0.0.3", port=5077,
        )
        # Must not raise TypeError comparing float with str
        assert len(listener.receivers) == 1

    def test_last_seen_updates_on_refresh(self):
        listener = DiscoveryListener()
        status = ReceiverStatus(device_name="B", host="10.0.0.4", port=5077)
        old = time.time() - 5
        status.last_seen = old
        listener._receivers["10.0.0.4:5077"] = status

        refreshed = ReceiverStatus(device_name="B", host="10.0.0.4", port=5077)
        listener._receivers["10.0.0.4:5077"] = refreshed
        assert listener._receivers["10.0.0.4:5077"].last_seen > old


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {
            "success": True,
            "filename": "shot.png",
            "received_at": "now",
        }

    def json(self):
        return self._payload


class TestUploadRetry:
    def test_upload_retried_once_after_connection_error(self, monkeypatch):
        client = _make_client()
        client._connected_receiver = ReceiverStatus(
            device_name="B", host="10.0.0.5", port=5077,
        )
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise requests.exceptions.ConnectionError("refused")
            return _FakeResponse()

        monkeypatch.setattr(requests, "post", fake_post)
        result = client.upload_screenshot(b"data", "shot.png")
        assert result.success
        assert len(calls) == 1 + config.UPLOAD_RETRIES

    def test_upload_reports_failure_after_retries_exhausted(self, monkeypatch):
        client = _make_client()
        client._connected_receiver = ReceiverStatus(
            device_name="B", host="10.0.0.6", port=5077,
        )
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(1)
            raise requests.exceptions.ConnectionError("refused")

        monkeypatch.setattr(requests, "post", fake_post)
        result = client.upload_screenshot(b"data", "shot.png")
        assert not result.success
        assert len(calls) == 1 + config.UPLOAD_RETRIES

    def test_retry_callback_reports_final_failure(self, monkeypatch):
        client = _make_client()
        client._connected_receiver = ReceiverStatus(
            device_name="B", host="10.0.0.7", port=5077,
        )

        def fake_post(*args, **kwargs):
            raise requests.exceptions.ConnectionError("refused")

        monkeypatch.setattr(requests, "post", fake_post)
        seen = []
        client.upload_screenshot(b"data", "shot.png",
                                 callback=lambda ok, resp: seen.append(ok))
        assert seen == [False]


class TestReconnect:
    def test_attempt_reconnect_fires_callback_when_receiver_reappears(self):
        client = _make_client()
        target = ReceiverStatus(device_name="B", host="10.0.0.9", port=5077)
        client.set_target(target)
        client.disconnect()
        assert not client.is_connected

        fired = []
        client.set_reconnect_callback(fired.append)

        # Receiver reappears in discovery
        client._listener._receivers["10.0.0.9:5077"] = ReceiverStatus(
            device_name="B", host="10.0.0.9", port=5077,
        )
        assert client.attempt_reconnect()
        assert client.is_connected
        assert len(fired) == 1
        assert fired[0].host == "10.0.0.9"

    def test_attempt_reconnect_false_when_receiver_absent(self):
        client = _make_client()
        client.set_target(ReceiverStatus(device_name="B", host="10.0.0.10", port=5077))
        client.disconnect()
        fired = []
        client.set_reconnect_callback(fired.append)
        assert not client.attempt_reconnect()
        assert fired == []

    def test_attempt_reconnect_ignores_stale_entries(self):
        client = _make_client()
        client.set_target(ReceiverStatus(device_name="B", host="10.0.0.11", port=5077))
        client.disconnect()
        stale = ReceiverStatus(device_name="B", host="10.0.0.11", port=5077)
        stale.last_seen = time.time() - config.PEER_STALE_TIMEOUT - 1
        client._listener._receivers["10.0.0.11:5077"] = stale
        assert not client.attempt_reconnect()

    def test_reconnect_loop_fires_when_receiver_reappears(self, monkeypatch):
        monkeypatch.setattr(config, "RECONNECT_INTERVAL", 0.05)
        client = _make_client()
        client.set_target(ReceiverStatus(device_name="B", host="10.0.0.12", port=5077))
        client.disconnect()

        fired = []
        client.start_reconnect(fired.append)
        try:
            time.sleep(0.1)
            assert fired == []
            client._listener._receivers["10.0.0.12:5077"] = ReceiverStatus(
                device_name="B", host="10.0.0.12", port=5077,
            )
            deadline = time.time() + 2
            while not fired and time.time() < deadline:
                time.sleep(0.02)
            assert len(fired) == 1
            assert client.is_connected
        finally:
            client.stop_reconnect()
