"""Tests for gesture recognition engine."""
import time
import math
import pytest
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from airshare.shared.models import HandData, GestureType
from airshare.sender.gesture_recognizer import GestureRecognizer


def make_hand_data(palm_x, palm_y, wrist_x=None, wrist_y=None):
    """Create a HandData with specific palm position."""
    if wrist_x is None:
        wrist_x = palm_x
    if wrist_y is None:
        wrist_y = palm_y + 0.1
    return HandData(
        detected=True,
        palm_center=(palm_x, palm_y),
        wrist=(wrist_x, wrist_y),
        index_tip=(palm_x + 0.02, palm_y - 0.05),
        landmarks=[(palm_x, palm_y, 0)] * 21,
        timestamp=time.time(),
    )


def make_gesture_sequence(start_x, start_y, dx_per_frame, dy_per_frame, frames):
    """Generate a sequence of HandData for a movement."""
    data_list = []
    for i in range(frames):
        t = time.time() + i * 0.033
        x = start_x + dx_per_frame * i
        y = start_y + dy_per_frame * i
        hd = HandData(
            detected=True,
            palm_center=(x, y),
            wrist=(x, y + 0.1),
            index_tip=(x + 0.02, y - 0.05),
            landmarks=[(x, y, 0)] * 21,
            timestamp=t,
        )
        data_list.append(hd)
    return data_list


class TestGestureRecognizer:

    def setup_method(self):
        self.rec = GestureRecognizer()

    def test_no_hand(self):
        """No hand detected returns NONE."""
        hd = HandData(detected=False)
        result = self.rec.update(hd)
        assert result.gesture == GestureType.NONE

    def test_small_movement_no_gesture(self):
        """Small movements should not trigger gestures."""
        for _ in range(10):
            hd = make_hand_data(0.5, 0.5)
            result = self.rec.update(hd)
        assert result.gesture == GestureType.NONE

    def test_upward_push_capture(self):
        """A clear upward push should be detected as CAPTURE."""
        # Generate upward movement (y decreases going up in normalized coords)
        sequence = make_gesture_sequence(0.5, 0.8, 0.0, -0.03, 25)
        results = []
        for hd in sequence:
            result = self.rec.update(hd)
            results.append(result)
        # Check if CAPTURE was triggered at any point during the sequence
        gestures = [r.gesture for r in results]
        assert GestureType.CAPTURE in gestures, \
            f"CAPTURE not detected. Gestures: {gestures}"

    def test_horizontal_throw_transfer(self):
        """A clear horizontal throw should be detected as TRANSFER."""
        self.rec.reset()
        # Generate rightward movement
        sequence = make_gesture_sequence(0.2, 0.5, 0.03, 0.0, 25)
        results = []
        for hd in sequence:
            result = self.rec.update(hd)
            results.append(result)
        # Check if TRANSFER was triggered at any point
        gestures = [r.gesture for r in results]
        assert GestureType.TRANSFER in gestures, \
            f"TRANSFER not detected. Gestures: {gestures}"

    def test_wrong_direction_no_gesture(self):
        """A leftward movement should NOT be detected as a transfer gesture."""
        self.rec.reset()
        # Generate leftward movement
        sequence = make_gesture_sequence(0.8, 0.5, -0.03, 0.0, 20)
        results = []
        for hd in sequence:
            result = self.rec.update(hd)
            results.append(result)
        # Should not be TRANSFER
        gestures = [r.gesture for r in results]
        assert GestureType.TRANSFER not in gestures

    def test_capture_then_ready_to_transfer(self):
        """After capture gesture, should allow transfer gesture."""
        self.rec.reset()
        # Perform capture
        seq = make_gesture_sequence(0.5, 0.8, 0.0, -0.03, 25)
        for hd in seq:
            self.rec.update(hd)
        # Reset and perform transfer
        self.rec.reset()
        seq = make_gesture_sequence(0.2, 0.5, 0.03, 0.0, 25)
        results = []
        for hd in seq:
            result = self.rec.update(hd)
            results.append(result)
        gestures = [r.gesture for r in results]
        assert GestureType.TRANSFER in gestures

    def test_reset(self):
        """Reset clears state."""
        self.rec.update(make_hand_data(0.5, 0.5))
        self.rec.update(make_hand_data(0.6, 0.5))
        self.rec.reset()
        result = self.rec.update(make_hand_data(0.3, 0.5))
        assert result.gesture == GestureType.NONE

    def test_movement_path(self):
        """Movement path tracks positions."""
        self.rec.update(make_hand_data(0.1, 0.1))
        self.rec.update(make_hand_data(0.2, 0.2))
        self.rec.update(make_hand_data(0.3, 0.3))
        path = self.rec.get_movement_path()
        assert len(path) == 3
        assert path[0] == (0.1, 0.1)
        assert path[2] == (0.3, 0.3)

    def test_capture_once_per_gesture(self):
        """Capture should not trigger twice from the same continuous gesture."""
        self.rec.reset()
        seq = make_gesture_sequence(0.5, 0.9, 0.0, -0.04, 30)
        capture_count = 0
        for hd in seq:
            result = self.rec.update(hd)
            if result.gesture == GestureType.CAPTURE:
                capture_count += 1
        # Should trigger exactly once
        assert capture_count == 1, f"Capture triggered {capture_count} times"
