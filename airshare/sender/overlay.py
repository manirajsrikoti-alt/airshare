"""Camera overlay and visual feedback for the sender."""
import cv2
import numpy as np
import logging
import time
import math

from airshare.shared.models import SenderState, GestureType

logger = logging.getLogger(__name__)

# Colors
COLOR_BG = (20, 20, 20)
COLOR_TEXT = (230, 230, 230)
COLOR_DIM = (120, 120, 120)
COLOR_ACCENT = (255, 180, 50)   # warm amber
COLOR_GREEN = (80, 200, 80)
COLOR_BLUE = (255, 160, 50)     # BGR
COLOR_RED = (80, 80, 255)
COLOR_WHITE = (255, 255, 255)

# State display mapping
_STATE_DISPLAY = {
    SenderState.IDLE: ("IDLE", COLOR_DIM),
    SenderState.READY: ("READY", COLOR_GREEN),
    SenderState.GESTURE_ARMED: ("GESTURE ARMED", COLOR_ACCENT),
    SenderState.CAPTURE_DETECTED: ("CAPTURING...", COLOR_BLUE),
    SenderState.CAPTURING: ("CAPTURING SCREEN...", COLOR_BLUE),
    SenderState.CAPTURED: ("✓ SCREEN CAPTURED", COLOR_GREEN),
    SenderState.READY_TO_TRANSFER: ("READY TO THROW →", COLOR_ACCENT),
    SenderState.TRANSFER_DETECTED: ("SENDING →", COLOR_BLUE),
    SenderState.SENDING: ("→ SENDING...", COLOR_BLUE),
    SenderState.TRANSFER_SUCCESS: ("✓ SENT!", COLOR_GREEN),
    SenderState.TRANSFER_FAILED: ("✗ FAILED", COLOR_RED),
    SenderState.CANCELLED: ("✋ CANCELLED", COLOR_DIM),
    SenderState.COOLDOWN: ("COOLDOWN...", COLOR_DIM),
    SenderState.CALIBRATING: ("CALIBRATING", COLOR_ACCENT),
    SenderState.CAMERA_ERROR: ("CAMERA ERROR", COLOR_RED),
}

_GESTURE_DISPLAY = {
    GestureType.NONE: ("—", COLOR_DIM),
    GestureType.GRAB: ("✊ GRAB", COLOR_BLUE),
    GestureType.FLICK: ("→ FLICK", COLOR_ACCENT),
    GestureType.CANCEL: ("✋ CANCEL", COLOR_RED),
}


class Overlay:
    """Draws the camera overlay UI."""

    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self._animation_t = 0.0

    def draw(self, frame: np.ndarray, state: SenderState,
             gesture_type: GestureType, confidence: float,
             hand_detected: bool, receiver_name: str,
             receiver_connected: bool, has_screenshot: bool,
             debug_mode: bool = False,
             movement_path: list = None) -> np.ndarray:
        """Draw the full overlay on the camera frame."""
        self._animation_t = time.time()

        # Semi-transparent panel at the top
        overlay = frame.copy()
        panel_h = 90 if not debug_mode else 140
        cv2.rectangle(overlay, (0, 0), (self.width, panel_h), (10, 10, 10), -1)
        frame = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

        # Title
        cv2.putText(frame, "AIRSHARE", (16, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_WHITE, 2, cv2.LINE_AA)

        # Status line 1: Camera + Hand
        cam_text = f"Camera {'●' if True else '○'}"
        cam_color = COLOR_GREEN
        cv2.putText(frame, cam_text, (16, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, cam_color, 1, cv2.LINE_AA)

        hand_text = f"Hand {'● Detected' if hand_detected else '○ Searching'}"
        hand_color = COLOR_GREEN if hand_detected else COLOR_DIM
        cv2.putText(frame, hand_text, (130, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, hand_color, 1, cv2.LINE_AA)

        # Status line 2: Gesture + Confidence
        gesture_name, gesture_color = _GESTURE_DISPLAY.get(gesture_type, ("—", COLOR_DIM))
        conf_text = f"Gesture: {gesture_name}  Conf: {confidence:.0%}"
        cv2.putText(frame, conf_text, (16, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, gesture_color, 1, cv2.LINE_AA)

        # Receiver info (top right)
        recv_text = f"Receiver: {receiver_name}"
        if receiver_connected:
            recv_color = COLOR_GREEN
            recv_text += " ●"
        else:
            recv_color = COLOR_DIM
            recv_text += " ○"
        (tw, _), _ = cv2.getTextSize(recv_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.putText(frame, recv_text, (self.width - tw - 16, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, recv_color, 1, cv2.LINE_AA)

        # State display
        state_name, state_color = _STATE_DISPLAY.get(state, ("UNKNOWN", COLOR_DIM))
        state_text = f"State: {state_name}"
        (tw2, _), _ = cv2.getTextSize(state_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(frame, state_text, (self.width - tw2 - 16, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, state_color, 1, cv2.LINE_AA)

        # Debug info
        if debug_mode:
            debug_y = 105
            debug_lines = [
                f"Confidence: {confidence:.2f}",
                f"State: {state.name}",
                f"Screenshot: {'Yes' if has_screenshot else 'No'}",
            ]
            for line in debug_lines:
                cv2.putText(frame, line, (16, debug_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_DIM, 1, cv2.LINE_AA)
                debug_y += 18

        # Draw movement path
        if movement_path and len(movement_path) > 1:
            self._draw_movement_path(frame, movement_path)

        # State-specific overlays
        self._draw_state_overlay(frame, state, receiver_name)

        # Bottom bar for captured screenshot preview
        if has_screenshot and state == SenderState.READY_TO_TRANSFER:
            self._draw_preview_bar(frame)

        return frame

    def _draw_movement_path(self, frame: np.ndarray, path: list):
        """Draw the hand movement trail."""
        h, w = frame.shape[:2]
        if len(path) < 2:
            return

        for i in range(1, len(path)):
            p1 = (int(path[i - 1][0] * w), int(path[i - 1][1] * h))
            p2 = (int(path[i][0] * w), int(path[i][1] * h))
            alpha = i / len(path)
            color = (int(50 + 150 * alpha), int(180 * alpha), int(255 * alpha))
            cv2.line(frame, p1, p2, color, 2, cv2.LINE_AA)

    def _draw_state_overlay(self, frame: np.ndarray, state: SenderState,
                            receiver_name: str):
        """Draw state-specific large overlays."""
        cx = self.width // 2
        cy = self.height // 2

        if state in (SenderState.CAPTURING, SenderState.CAPTURE_DETECTED):
            # Pulsing capture indicator
            pulse = 0.7 + 0.3 * math.sin(self._animation_t * 6)
            text = "CAPTURING..."
            scale = 1.0
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
            x = cx - tw // 2
            y = cy + th // 2
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, COLOR_BLUE, 2, cv2.LINE_AA)

        elif state == SenderState.TRANSFER_SUCCESS:
            text = "✓ SENT!"
            scale = 1.2
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
            x = cx - tw // 2
            y = cy + th // 2
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, COLOR_GREEN, 3, cv2.LINE_AA)

        elif state == SenderState.TRANSFER_FAILED:
            text = "TRANSFER FAILED"
            scale = 1.0
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
            x = cx - tw // 2
            y = cy + th // 2
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, COLOR_RED, 2, cv2.LINE_AA)

        elif state == SenderState.SENDING:
            # Animated sending indicator
            dots = "." * (int(self._animation_t * 4) % 4)
            text = f"SENDING{dots}"
            scale = 1.0
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
            x = cx - tw // 2
            y = cy + th // 2
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, COLOR_BLUE, 2, cv2.LINE_AA)

        elif state == SenderState.CAMERA_ERROR:
            text1 = "CAMERA ERROR"
            text2 = "Please check camera permissions"
            cv2.putText(frame, text1, (cx - 120, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLOR_RED, 2, cv2.LINE_AA)
            cv2.putText(frame, text2, (cx - 140, cy + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_DIM, 1, cv2.LINE_AA)

    def _draw_preview_bar(self, frame: np.ndarray):
        """Draw a hint bar at the bottom for the capture preview state."""
        bar_h = 50
        y_start = self.height - bar_h
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, y_start), (self.width, self.height),
                      (10, 10, 10), -1)
        frame[:] = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0)

        text = "→ Flick to transfer screenshot"
        cv2.putText(frame, text, (16, y_start + 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_ACCENT, 1, cv2.LINE_AA)

    def draw_calibrating(self, frame: np.ndarray, phase: str,
                         count: int, target: int) -> np.ndarray:
        """Draw calibration mode overlay."""
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (self.width, self.height), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

        cx = self.width // 2
        cy = self.height // 2

        cv2.putText(frame, "CALIBRATION MODE", (cx - 150, cy - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLOR_ACCENT, 2, cv2.LINE_AA)

        cv2.putText(frame, f"Perform: {phase}", (cx - 120, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_WHITE, 1, cv2.LINE_AA)

        cv2.putText(frame, f"Samples: {count}/{target}", (cx - 80, cy + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_BLUE, 1, cv2.LINE_AA)

        cv2.putText(frame, "Press C to finish", (cx - 90, cy + 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_DIM, 1, cv2.LINE_AA)

        return frame
