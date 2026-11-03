"""Tests for the Huawei-style gesture set: fist-grab, flick, palm-cancel."""
import time
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from airshare import config
from airshare.shared.models import HandData, GestureType
from airshare.sender.gesture_recognizer import GestureRecognizer


def make_hand_data(palm_x, palm_y, is_fist=False):
    """Create a HandData with a specific palm position and fist state."""
    return HandData(
        detected=True,
        palm_center=(palm_x, palm_y),
        wrist=(palm_x, palm_y + 0.1),
        index_tip=(palm_x + 0.02, palm_y - 0.05),
        landmarks=[(palm_x, palm_y, 0)] * 21,
        is_fist=is_fist,
        timestamp=time.time(),
    )


def make_open_sequence(frames, start_x=0.5, start_y=0.5, dx=0.0, dy=0.0):
    """Sequence of open-palm (non-fist) frames."""
    return [make_hand_data(start_x + dx * i, start_y + dy * i, is_fist=False)
            for i in range(frames)]


def make_fist_sequence(frames, palm_x=0.5, palm_y=0.5):
    """Sequence of fist frames held still."""
    return [make_hand_data(palm_x, palm_y, is_fist=True) for _ in range(frames)]


class TestGestureRecognizer:

    def setup_method(self):
        self.rec = GestureRecognizer()

    def test_no_hand(self):
        """No hand detected returns NONE."""
        result = self.rec.update(HandData(detected=False))
        assert result.gesture == GestureType.NONE

    def test_stationary_open_hand_below_cancel_hold_no_gesture(self):
        """Open palm held fewer than CANCEL_HOLD_FRAMES yields nothing."""
        for hd in make_open_sequence(config.CANCEL_HOLD_FRAMES - 5):
            result = self.rec.update(hd)
        assert result.gesture == GestureType.NONE

    def test_open_to_fist_grab(self):
        """Open palm followed by a fist held GRAB_HOLD_FRAMES yields GRAB."""
        for hd in make_open_sequence(5):
            self.rec.update(hd)
        gestures = []
        for hd in make_fist_sequence(config.GRAB_HOLD_FRAMES):
            gestures.append(self.rec.update(hd).gesture)
        assert GestureType.GRAB in gestures, f"GRAB not detected. Gestures: {gestures}"

    def test_fist_held_less_than_grab_hold_no_grab(self):
        """Fist held for fewer than GRAB_HOLD_FRAMES frames yields NONE."""
        for hd in make_open_sequence(5):
            self.rec.update(hd)
        gestures = []
        for hd in make_fist_sequence(config.GRAB_HOLD_FRAMES - 1):
            gestures.append(self.rec.update(hd).gesture)
        assert GestureType.GRAB not in gestures

    def test_fist_without_prior_open_no_grab(self):
        """A fist that appears with no preceding open palm is not a grab."""
        gestures = []
        for hd in make_fist_sequence(config.GRAB_HOLD_FRAMES + 4):
            gestures.append(self.rec.update(hd).gesture)
        assert GestureType.GRAB not in gestures

    def test_grab_only_once_per_grasp(self):
        """Holding the fist past the hold threshold does not re-trigger GRAB."""
        for hd in make_open_sequence(5):
            self.rec.update(hd)
        grab_count = 0
        for hd in make_fist_sequence(config.GRAB_HOLD_FRAMES + 10):
            if self.rec.update(hd).gesture == GestureType.GRAB:
                grab_count += 1
        assert grab_count == 1, f"GRAB triggered {grab_count} times"

    def test_fast_horizontal_flick(self):
        """Fast horizontal palm movement above the velocity threshold yields FLICK."""
        self.rec.reset()
        gestures = []
        for hd in make_open_sequence(8, start_x=0.2, dx=0.06):
            gestures.append(self.rec.update(hd).gesture)
        assert GestureType.FLICK in gestures, f"FLICK not detected. Gestures: {gestures}"

    def test_slow_horizontal_movement_no_flick(self):
        """Slow horizontal movement stays below the flick threshold."""
        self.rec.reset()
        gestures = []
        for hd in make_open_sequence(10, start_x=0.3, dx=0.005):
            gestures.append(self.rec.update(hd).gesture)
        assert GestureType.FLICK not in gestures

    def test_open_palm_held_cancel(self):
        """Open palm held CANCEL_HOLD_FRAMES yields CANCEL."""
        self.rec.reset()
        gestures = []
        for hd in make_open_sequence(config.CANCEL_HOLD_FRAMES + 5):
            gestures.append(self.rec.update(hd).gesture)
        assert GestureType.CANCEL in gestures, f"CANCEL not detected. Gestures: {gestures}"

    def test_cancel_only_once(self):
        """A held open palm triggers CANCEL once, not every frame."""
        self.rec.reset()
        cancel_count = 0
        for hd in make_open_sequence(config.CANCEL_HOLD_FRAMES + 15):
            if self.rec.update(hd).gesture == GestureType.CANCEL:
                cancel_count += 1
        assert cancel_count == 1, f"CANCEL triggered {cancel_count} times"

    def test_reset(self):
        """Reset clears state."""
        self.rec.update(make_hand_data(0.5, 0.5))
        self.rec.update(make_hand_data(0.5, 0.5, is_fist=True))
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
