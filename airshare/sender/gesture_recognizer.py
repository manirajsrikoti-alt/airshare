"""Gesture recognition engine for the Huawei-style gesture set.

Recognizes:
- GRAB:   open palm transitions to a fist, held for GRAB_HOLD_FRAMES.
- FLICK:  fast horizontal palm movement above the velocity threshold.
- CANCEL: open palm held still for CANCEL_HOLD_FRAMES.
"""
import time
import logging
from collections import deque

from airshare import config
from airshare.shared.models import (
    HandData, MovementFrame, GestureResult, GestureType
)

logger = logging.getLogger(__name__)


class GestureRecognizer:
    """Recognizes fist-grab, flick, and palm-cancel gestures."""

    def __init__(self):
        self._history: deque[MovementFrame] = deque(maxlen=config.MOVEMENT_HISTORY_LENGTH)
        self._gesture_cooldown_until: float = 0.0  # Prevents re-triggering

        self._fist_frames: int = 0        # consecutive fist frames
        self._open_frames: int = 0        # consecutive still open-palm frames
        self._grab_armed: bool = False    # open palm seen; a fist can now grab

        self.grab_hold_frames = config.GRAB_HOLD_FRAMES
        self.cancel_hold_frames = config.CANCEL_HOLD_FRAMES
        self.flick_min_frame_displacement = config.FLICK_MIN_FRAME_DISPLACEMENT
        self.flick_min_total_displacement = config.FLICK_MIN_TOTAL_DISPLACEMENT
        self.flick_window_frames = config.FLICK_WINDOW_FRAMES
        self.cancel_max_frame_displacement = config.CANCEL_MAX_FRAME_DISPLACEMENT

    def update(self, hand_data: HandData) -> GestureResult:
        """Process a new frame and return gesture result."""
        if not hand_data.detected:
            self._on_hand_lost()
            return GestureResult(gesture=GestureType.NONE, confidence=0.0)

        frame = MovementFrame(
            palm_x=hand_data.palm_center[0],
            palm_y=hand_data.palm_center[1],
            wrist_x=hand_data.wrist[0],
            wrist_y=hand_data.wrist[1],
            timestamp=hand_data.timestamp or time.time(),
        )
        self._history.append(frame)

        if time.time() < self._gesture_cooldown_until:
            return GestureResult(gesture=GestureType.NONE, confidence=0.0)

        if hand_data.is_fist:
            return self._update_fist()
        return self._update_open_palm()

    def _update_fist(self) -> GestureResult:
        """Track a held fist; fire GRAB once the hold threshold is reached."""
        self._fist_frames += 1
        self._open_frames = 0
        if self._grab_armed and self._fist_frames == self.grab_hold_frames:
            self._grab_armed = False
            self._gesture_cooldown_until = time.time() + config.COOLDOWN_SECONDS
            return GestureResult(
                gesture=GestureType.GRAB,
                confidence=1.0,
                frame_count=self._fist_frames,
            )
        return GestureResult(gesture=GestureType.NONE, frame_count=self._fist_frames)

    def _update_open_palm(self) -> GestureResult:
        """Track open-palm frames; detect flick and held-palm cancel."""
        self._fist_frames = 0
        self._grab_armed = True

        frame_displacement = self._last_frame_displacement()
        if frame_displacement > self.cancel_max_frame_displacement:
            self._open_frames = 0
        else:
            self._open_frames += 1
            if self._open_frames >= self.cancel_hold_frames:
                self._open_frames = 0
                self._gesture_cooldown_until = time.time() + config.COOLDOWN_SECONDS
                return GestureResult(
                    gesture=GestureType.CANCEL,
                    confidence=1.0,
                    frame_count=self.cancel_hold_frames,
                )

        flick = self._detect_flick()
        if flick is not None:
            return flick

        return GestureResult(gesture=GestureType.NONE, frame_count=self._open_frames)

    def _detect_flick(self) -> GestureResult | None:
        """Detect fast horizontal movement over the recent flick window."""
        if len(self._history) < 2:
            return None

        history = list(self._history)[-self.flick_window_frames:]
        dx = history[-1].palm_x - history[0].palm_x
        dy = history[-1].palm_y - history[0].palm_y
        avg_frame_dx = abs(dx) / (len(history) - 1)

        if (avg_frame_dx >= self.flick_min_frame_displacement and
                abs(dx) >= self.flick_min_total_displacement and
                abs(dx) > abs(dy)):
            self._gesture_cooldown_until = time.time() + config.COOLDOWN_SECONDS
            self._history.clear()
            self._open_frames = 0
            self._grab_armed = False
            return GestureResult(
                gesture=GestureType.FLICK,
                confidence=1.0,
                displacement=abs(dx),
                velocity=avg_frame_dx,
                direction="right" if dx > 0 else "left",
            )
        return None

    def _last_frame_displacement(self) -> float:
        """Palm displacement between the two most recent frames."""
        if len(self._history) < 2:
            return 0.0
        history = list(self._history)
        prev, cur = history[-2], history[-1]
        return ((cur.palm_x - prev.palm_x) ** 2 + (cur.palm_y - prev.palm_y) ** 2) ** 0.5

    def _on_hand_lost(self):
        """Handle hand disappearing from view."""
        self._fist_frames = 0
        self._open_frames = 0
        self._grab_armed = False

    def reset(self):
        """Full reset of recognizer state."""
        self._history.clear()
        self._gesture_cooldown_until = 0.0
        self._on_hand_lost()

    def get_movement_path(self) -> list[tuple[float, float]]:
        """Get the recent movement path for visualization."""
        return [(f.palm_x, f.palm_y) for f in self._history]
