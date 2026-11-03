"""Tests for shared protocol and models."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from airshare.shared.protocol import (
    TransferRequest, TransferResponse, ReceiverStatus, DeviceInfo
)
from airshare.shared.models import (
    SenderState, GestureType, HandData, MovementFrame,
    GestureResult, CalibrationData
)


class TestTransferResponse:

    def test_from_dict(self):
        """Parse response from dict."""
        resp = TransferResponse.from_dict({
            "success": True,
            "filename": "test.png",
            "received_at": "2026-08-31 10:00:00",
        })
        assert resp.success
        assert resp.filename == "test.png"

    def test_from_dict_empty(self):
        """Parse empty dict."""
        resp = TransferResponse.from_dict({})
        assert not resp.success
        assert resp.filename == ""


class TestReceiverStatus:

    def test_to_broadcast(self):
        """Broadcast message format."""
        status = ReceiverStatus(device_name="Laptop B", port=5000, host="192.168.1.100")
        msg = status.to_broadcast()
        assert msg.startswith("AIRSHARE_RECEIVER")
        assert "device_name=Laptop B" in msg
        assert "port=5000" in msg

    def test_from_broadcast(self):
        """Parse broadcast message."""
        msg = "AIRSHARE_RECEIVER|device_name=My Laptop|port=5001|host=10.0.0.1"
        status = ReceiverStatus.from_broadcast(msg)
        assert status is not None
        assert status.device_name == "My Laptop"
        assert status.port == 5001
        assert status.host == "10.0.0.1"

    def test_from_broadcast_invalid(self):
        """Invalid broadcast returns None."""
        assert ReceiverStatus.from_broadcast("NOT AIRSHARE") is None
        assert ReceiverStatus.from_broadcast("") is None


class TestDeviceInfo:

    def test_to_dict(self):
        """Device info serializes correctly."""
        dev = DeviceInfo(name="Laptop B", host="192.168.1.1", port=5000)
        d = dev.to_dict()
        assert d["name"] == "Laptop B"
        assert d["url"] == "http://192.168.1.1:5000"


class TestModels:

    def test_hand_data_defaults(self):
        """HandData has sensible defaults."""
        hd = HandData()
        assert not hd.detected
        assert hd.palm_center == (0.5, 0.5)

    def test_gesture_result_not_detected(self):
        """Default GestureResult is NONE."""
        gr = GestureResult()
        assert not gr.detected
        assert gr.gesture == GestureType.NONE

    def test_gesture_result_detected(self):
        """CAPTURE gesture is detected."""
        gr = GestureResult(gesture=GestureType.CAPTURE, confidence=0.9)
        assert gr.detected

    def test_sender_state_enum(self):
        """All expected states exist."""
        expected = [
            "IDLE", "READY", "GESTURE_ARMED", "CAPTURE_DETECTED",
            "CAPTURING", "CAPTURED", "READY_TO_TRANSFER",
            "TRANSFER_DETECTED", "SENDING", "TRANSFER_SUCCESS",
            "TRANSFER_FAILED", "COOLDOWN", "CALIBRATING", "CAMERA_ERROR",
        ]
        for name in expected:
            assert hasattr(SenderState, name)

    def test_movement_frame(self):
        """MovementFrame position property."""
        mf = MovementFrame(palm_x=0.3, palm_y=0.7)
        assert mf.position == (0.3, 0.7)
