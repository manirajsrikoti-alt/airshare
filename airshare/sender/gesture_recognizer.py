"""Gesture recognition engine using movement history and landmark geometry."""
import time
import logging
from collections import deque

import numpy as np

from airshare import config
from airshare.shared.models import (
    HandData, MovementFrame, GestureResult, GestureType
)

logger = logging.getLogger(__name__)


class GestureRecognizer:
    """Recognizes capture (upward) and transfer (throw) gestures from hand movement history."""

    def __init__(self):
        self._history: deque[MovementFrame] = deque(maxlen=config.MOVEMENT_HISTORY_LENGTH)
        self._gesture_start_frame: MovementFrame | None = None
        self._gesture_frame_count: int = 0
        self._in_gesture: bool = False
        self._gesture_cooldown_until: float = 0.0  # Prevents re-triggering

        # Thresholds (can be overridden by calibration)
        self.capture_min_displacement = config.CAPTURE_MIN_DISPLACEMENT
        self.capture_min_velocity = config.CAPTURE_MIN_VELOCITY
        self.capture_min_frames = config.CAPTURE_MIN_FRAMES
        self.capture_max_frames = config.CAPTURE_MAX_FRAMES
        self.capture_min_direction_ratio = config.CAPTURE_MIN_DIRECTION_RATIO
        self.capture_velocity_ratio = config.CAPTURE_VELOCITY_RATIO

        self.transfer_min_displacement = config.TRANSFER_MIN_DISPLACEMENT
        self.transfer_min_velocity = config.TRANSFER_MIN_VELOCITY
        self.transfer_min_frames = config.TRANSFER_MIN_FRAMES
        self.transfer_max_frames = config.TRANSFER_MAX_FRAMES
        self.transfer_min_direction_ratio = config.TRANSFER_MIN_DIRECTION_RATIO
        self.transfer_velocity_ratio = config.TRANSFER_VELOCITY_RATIO

    def update(self, hand_data: HandData) -> GestureResult:
        """Process a new frame and return gesture result."""
        if not hand_data.detected:
            self._on_hand_lost()
            return GestureResult(gesture=GestureType.NONE, confidence=0.0)

        # Create movement frame
        frame = MovementFrame(
            palm_x=hand_data.palm_center[0],
            palm_y=hand_data.palm_center[1],
            wrist_x=hand_data.wrist[0],
            wrist_y=hand_data.wrist[1],
            timestamp=hand_data.timestamp or time.time(),
        )

        # Add to history
        self._history.append(frame)

        # Check cooldown
        now = time.time()
        if now < self._gesture_cooldown_until:
            return GestureResult(gesture=GestureType.NONE, confidence=0.0)

        # Track active gesture
        if self._in_gesture:
            self._gesture_frame_count += 1
            # Check for gesture timeout
            if self._gesture_frame_count > max(self.capture_max_frames, self.transfer_max_frames):
                self._reset_gesture()
                return GestureResult(gesture=GestureType.NONE, confidence=0.0)

        # Need enough frames to analyze
        if len(self._history) < 3:
            return GestureResult(gesture=GestureType.NONE, confidence=0.0)

        return self._analyze_movement()

    def _analyze_movement(self) -> GestureResult:
        """Analyze the movement history for gestures."""
        history = list(self._history)
        start = history[0]
        end = history[-1]

        # Calculate displacement
        dx = end.palm_x - start.palm_x
        dy = end.palm_y - start.palm_y
        displacement = np.sqrt(dx**2 + dy**2)

        # Calculate velocity (pixels per second)
        dt = end.timestamp - start.timestamp
        if dt <= 0:
            dt = 0.033  # ~30fps fallback
        velocity = displacement / dt

        # Direction analysis
        if abs(dx) < 0.001 and abs(dy) < 0.001:
            return GestureResult(
                gesture=GestureType.NONE, confidence=0.0,
                displacement=displacement, velocity=velocity, frame_count=self._gesture_frame_count,
            )

        # Check upward gesture (capture)
        # dy is positive when hand moves up in normalized coords (y decreases = upward)
        up_amount = -dy  # positive = upward movement
        if up_amount > 0 and displacement > 0:
            vertical_ratio = up_amount / displacement
            if (vertical_ratio >= self.capture_velocity_ratio and
                    displacement >= self.capture_min_displacement and
                    velocity >= self.capture_min_velocity):
                # Check direction consistency
                direction_score = self._check_direction_consistency("vertical")
                if direction_score >= self.capture_min_direction_ratio:
                    if not self._in_gesture:
                        self._in_gesture = True
                        self._gesture_start_frame = start
                        self._gesture_frame_count = 0

                    confidence = self._calculate_confidence(
                        displacement, velocity, direction_score,
                        self.capture_min_displacement, self.capture_min_velocity,
                    )

                    if (self._gesture_frame_count >= self.capture_min_frames and
                            confidence >= 0.5):
                        self._gesture_cooldown_until = time.time() + config.COOLDOWN_SECONDS
                        self._reset_gesture()
                        return GestureResult(
                            gesture=GestureType.CAPTURE,
                            confidence=confidence,
                            displacement=displacement,
                            velocity=velocity,
                            direction="upward",
                            frame_count=self._gesture_frame_count,
                        )

        # Check horizontal throw gesture (transfer) - must be rightward
        right_amount = dx  # positive = rightward
        if right_amount > 0 and displacement > 0:
            horizontal_ratio = right_amount / displacement
            if (horizontal_ratio >= self.transfer_velocity_ratio and
                    displacement >= self.transfer_min_displacement and
                    velocity >= self.transfer_min_velocity):
                direction_score = self._check_direction_consistency("horizontal")
                if direction_score >= self.transfer_min_direction_ratio:
                    if not self._in_gesture:
                        self._in_gesture = True
                        self._gesture_start_frame = start
                        self._gesture_frame_count = 0

                    confidence = self._calculate_confidence(
                        displacement, velocity, direction_score,
                        self.transfer_min_displacement, self.transfer_min_velocity,
                    )

                    if (self._gesture_frame_count >= self.transfer_min_frames and
                            confidence >= 0.5):
                        self._gesture_cooldown_until = time.time() + config.COOLDOWN_SECONDS
                        self._reset_gesture()
                        return GestureResult(
                            gesture=GestureType.TRANSFER,
                            confidence=confidence,
                            displacement=displacement,
                            velocity=velocity,
                            direction="outward",
                            frame_count=self._gesture_frame_count,
                        )

        return GestureResult(
            gesture=GestureType.NONE,
            confidence=0.0,
            displacement=displacement,
            velocity=velocity,
            frame_count=self._gesture_frame_count,
        )

    def _check_direction_consistency(self, axis: str) -> float:
        """Check how consistently the hand moves in one direction."""
        if len(self._history) < 3:
            return 0.0

        history = list(self._history)
        consistent_count = 0
        total_count = len(history) - 1

        for i in range(1, len(history)):
            if axis == "vertical":
                # Moving upward = consistent if each step is upward or neutral
                dy = history[i].palm_y - history[i - 1].palm_y
                if dy <= 0.005:  # upward or neutral (y decreases going up)
                    consistent_count += 1
            else:
                # Moving right = consistent
                dx = history[i].palm_x - history[i - 1].palm_x
                if abs(dx) > 0.002:  # has horizontal component
                    consistent_count += 1

        return consistent_count / total_count if total_count > 0 else 0.0

    def _calculate_confidence(self, displacement: float, velocity: float,
                              direction_score: float,
                              min_disp: float, min_vel: float) -> float:
        """Calculate a confidence score from 0.0 to 1.0."""
        disp_score = min(displacement / (min_disp * 2), 1.0)
        vel_score = min(velocity / (min_vel * 2), 1.0)

        confidence = (
            0.3 * disp_score +
            0.3 * vel_score +
            0.4 * direction_score
        )
        return min(max(confidence, 0.0), 1.0)

    def _on_hand_lost(self):
        """Handle hand disappearing from view."""
        # Don't immediately reset - use grace period
        pass

    def _reset_gesture(self):
        """Reset gesture tracking state."""
        self._in_gesture = False
        self._gesture_start_frame = None
        self._gesture_frame_count = 0
        self._history.clear()  # Clear history to prevent re-triggering

    def reset(self):
        """Full reset of recognizer state."""
        self._history.clear()
        self._reset_gesture()
        self._gesture_cooldown_until = 0.0

    def get_movement_path(self) -> list[tuple[float, float]]:
        """Get the recent movement path for visualization."""
        return [(f.palm_x, f.palm_y) for f in self._history]
