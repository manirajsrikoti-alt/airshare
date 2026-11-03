"""AirShare Sender — Main application entry point.

Run with: python -m airshare.sender.main
"""
import cv2
import sys
import time
import logging
import json
import numpy as np

from airshare import config
from airshare.shared.models import SenderState, GestureType, HandData
from airshare.sender.camera import Camera
from airshare.sender.hand_tracker import HandTracker
from airshare.sender.gesture_recognizer import GestureRecognizer
from airshare.sender.gesture_state import GestureStateMachine
from airshare.sender.screenshot import ScreenshotCapture
from airshare.sender.network_client import NetworkClient
from airshare.sender.overlay import Overlay

logger = logging.getLogger(__name__)


class AirShareSender:
    """Main sender application."""

    def __init__(self):
        self.camera = Camera()
        self.tracker = HandTracker()
        self.gesture = GestureRecognizer()
        self.state = GestureStateMachine()
        self.screenshot = ScreenshotCapture()
        self.network = NetworkClient()
        self.overlay = Overlay()

        self._debug_mode = config.DEBUG_MODE
        self._running = False
        self._last_gesture_result = None
        self._hand_lost_time = 0.0
        self._cooldown_until = 0.0
        self._calibration_mode = False
        self._calibration_samples = []
        self._calibration_target = 10
        self._gestures_enabled = False

    @property
    def gestures_enabled(self) -> bool:
        return self._gestures_enabled

    def set_gestures_enabled(self, enabled: bool):
        """Toggle webcam gesture tracking (OFF by default)."""
        self._gestures_enabled = bool(enabled)
        if not self._gestures_enabled:
            self.gesture.reset()
        logger.info(f"Gesture tracking: {'ON' if self._gestures_enabled else 'OFF'}")

    def initialize(self) -> bool:
        """Initialize camera, tracker, and screenshot modules. Returns True on success."""
        logger.info("=" * 50)
        logger.info("AirShare Sender Starting...")
        logger.info("=" * 50)

        # Initialize camera
        if not self.camera.initialize():
            logger.error("Failed to initialize camera")
            self.state.force_state(SenderState.CAMERA_ERROR)
            return False

        # Initialize hand tracker
        if not self.tracker.initialize():
            logger.error("Failed to initialize hand tracker")
            return False

        # Initialize screenshot
        if not self.screenshot.initialize():
            logger.error("Failed to initialize screenshot module")
            return False

        # Set up state listener
        self.state.on_transition(self._on_state_change)

        # Start discovery
        self.network.start_discovery(self._on_receiver_found)

        self.state.force_state(SenderState.READY)
        self.overlay = Overlay(
            width=self.camera.get_frame_width(),
            height=self.camera.get_frame_height(),
        )
        return True

    def run(self):
        """Run the main loop after a successful initialize()."""
        self._running = True
        logger.info("Sender ready. Press ESC to exit.")
        logger.info("Keyboard shortcuts: S=capture, T=transfer, C=calibrate, D=debug, G=gestures")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self._cleanup()

    def start(self):
        """Initialize and run the sender application."""
        if not self.initialize():
            self._show_camera_error()
            return
        self.run()

    def stop(self):
        """Request the main loop to exit."""
        self._running = False

    def _main_loop(self):
        """Main processing loop."""
        while self._running:
            ret, frame = self.camera.read()
            if not ret or frame is None:
                continue

            if self._gestures_enabled:
                # Convert to RGB for MediaPipe
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Process hand tracking
                hand_data = self.tracker.process(frame_rgb)

                # Update hand lost timer
                if not hand_data.detected:
                    if self._hand_lost_time == 0:
                        self._hand_lost_time = time.time()
                    elif (time.time() - self._hand_lost_time) * 1000 > config.HAND_LOST_GRACE_MS:
                        self.gesture.reset()
                else:
                    self._hand_lost_time = 0

                # Process gesture (if not in cooldown)
                if time.time() > self._cooldown_until:
                    if self.state.ready_for_new_action():
                        gesture_result = self.gesture.update(hand_data)
                        self._last_gesture_result = gesture_result
                        self._handle_gesture(gesture_result)
                    elif not self.state.is_capturing() and not self.state.is_sending():
                        gesture_result = self.gesture.update(hand_data)
                else:
                    self.gesture.update(hand_data)
            else:
                hand_data = HandData()

            # Draw overlay
            gesture_type = self._last_gesture_result.gesture if self._last_gesture_result else GestureType.NONE
            confidence = self._last_gesture_result.confidence if self._last_gesture_result else 0.0
            movement_path = self.gesture.get_movement_path()

            if self._calibration_mode:
                frame = self.overlay.draw_calibrating(
                    frame,
                    "FIST GRAB" if len(self._calibration_samples) < self._calibration_target else "FLICK",
                    len(self._calibration_samples),
                    self._calibration_target * 2,
                )
            else:
                frame = self.overlay.draw(
                    frame,
                    self.state.state,
                    gesture_type,
                    confidence,
                    hand_data.detected,
                    self.network.receiver_name,
                    self.network.is_connected,
                    self.screenshot.has_screenshot,
                    self._debug_mode,
                    movement_path,
                )

            # Draw landmarks in debug mode
            if self._debug_mode and hand_data.detected:
                self.tracker.draw_landmarks(frame, hand_data)

            cv2.imshow("AirShare Sender", frame)

            # Handle keyboard
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                self._running = False
            elif key == ord('s') or key == ord('S'):
                self._manual_capture()
            elif key == ord('t') or key == ord('T'):
                self._manual_transfer()
            elif key == ord('c') or key == ord('C'):
                self._toggle_calibration()
            elif key == ord('d') or key == ord('D'):
                self._debug_mode = not self._debug_mode
                logger.info(f"Debug mode: {'ON' if self._debug_mode else 'OFF'}")
            elif key == ord('g') or key == ord('G'):
                self.set_gestures_enabled(not self._gestures_enabled)

    def _handle_gesture(self, result):
        """Handle gesture detection results with state machine."""
        if result.gesture == GestureType.GRAB and result.confidence >= 0.5:
            if self.state.transition(SenderState.CAPTURE_DETECTED):
                self._perform_capture()
        elif result.gesture == GestureType.FLICK and result.confidence >= 0.5:
            if self.state.state == SenderState.READY_TO_TRANSFER:
                if self.state.transition(SenderState.TRANSFER_DETECTED):
                    self._perform_transfer()
        elif result.gesture == GestureType.CANCEL and result.confidence >= 0.5:
            if self.state.transition(SenderState.CANCELLED):
                logger.info("Gesture cancelled by open palm")
                self.gesture.reset()
                self.state.transition(SenderState.READY)

    def _perform_capture(self):
        """Capture a screenshot."""
        self.state.transition(SenderState.CAPTURING)
        self.overlay.animations.start_grab(
            center=(self.overlay.width // 2, self.overlay.height // 2))
        filepath = self.screenshot.capture()
        if filepath:
            self.state.transition(SenderState.CAPTURED)
            time.sleep(0.1)
            self.state.transition(SenderState.READY_TO_TRANSFER)
            self.gesture.reset()
            logger.info(f"Screenshot ready: {filepath}")
        else:
            self.state.transition(SenderState.TRANSFER_FAILED)
            time.sleep(1.0)
            self.state.transition(SenderState.READY)

    def _perform_transfer(self):
        """Transfer the screenshot to the connected receiver."""
        if not self.network.is_connected:
            logger.warning("No receiver connected for transfer")
            self.state.transition(SenderState.TRANSFER_FAILED)
            time.sleep(1.0)
            self.state.transition(SenderState.READY)
            return

        self.state.transition(SenderState.SENDING)
        thumb = self._make_fly_thumbnail()
        if thumb is not None:
            self.overlay.animations.start_fly(thumb, edge="right")
        data = self.screenshot.get_screenshot_data()
        if not data:
            logger.error("No screenshot to transfer")
            self.state.transition(SenderState.TRANSFER_FAILED)
            time.sleep(1.0)
            self.state.transition(SenderState.READY)
            return

        file_data, filename = data
        response = self.network.upload_screenshot(
            file_data, filename, sender_name="AirShare Sender",
            callback=self._on_transfer_complete,
        )

    def _make_fly_thumbnail(self):
        """Decode the captured screenshot into a thumbnail for the fly animation."""
        data = self.screenshot.get_screenshot_data()
        if not data:
            return None
        file_data, _ = data
        buf = np.frombuffer(file_data, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return None
        tw = max(1, int(self.overlay.width * config.THUMB_SCALE_END))
        th = max(1, int(self.overlay.height * config.THUMB_SCALE_END))
        return cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)

    def _on_transfer_complete(self, success, response):
        """Called when transfer finishes (from background thread)."""
        if success:
            logger.info(f"Transfer successful: {response.filename}")
            self.state.transition(SenderState.TRANSFER_SUCCESS)
            time.sleep(2.0)
            self.state.force_state(SenderState.READY)
            self._cooldown_until = time.time() + config.COOLDOWN_SECONDS
        else:
            logger.error(f"Transfer failed: {response.error}")
            self.state.transition(SenderState.TRANSFER_FAILED)
            time.sleep(1.5)
            self.state.transition(SenderState.READY)

    def _manual_capture(self):
        """Keyboard-triggered capture (S key)."""
        if self.state.ready_for_new_action():
            logger.info("Manual capture triggered")
            self.state.transition(SenderState.CAPTURE_DETECTED)
            self._perform_capture()

    def _manual_transfer(self):
        """Keyboard-triggered transfer (T key)."""
        if self.state.state == SenderState.READY_TO_TRANSFER:
            logger.info("Manual transfer triggered")
            self.state.transition(SenderState.TRANSFER_DETECTED)
            self._perform_transfer()

    def _on_receiver_found(self, receiver):
        """Called when a receiver is discovered."""
        logger.info(f"Receiver discovered: {receiver.device_name}")

    def _on_state_change(self, old_state, new_state):
        """State change callback."""
        if new_state == SenderState.CAPTURE_DETECTED:
            pass  # capture happens immediately
        elif new_state == SenderState.TRANSFER_SUCCESS:
            self.gesture.reset()

    def _toggle_calibration(self):
        """Toggle calibration mode."""
        if self._calibration_mode:
            self._finish_calibration()
        else:
            self._calibration_mode = True
            self._calibration_samples = []
            self.state.force_state(SenderState.CALIBRATING)
            logger.info("Calibration mode started")

    def _finish_calibration(self):
        """Finish calibration and save results."""
        self._calibration_mode = False
        self.state.force_state(SenderState.READY)

        if self._calibration_samples:
            # Calculate recommended thresholds
            displacements = [s['displacement'] for s in self._calibration_samples]
            velocities = [s['velocity'] for s in self._calibration_samples]

            avg_disp = np.mean(displacements)
            avg_vel = np.mean(velocities)

            # Save calibration data
            cal = {
                "capture_avg_displacement": float(avg_disp),
                "capture_avg_velocity": float(avg_vel),
                "recommended_min_displacement": float(avg_disp * 0.6),
                "recommended_min_velocity": float(avg_vel * 0.5),
                "sample_count": len(self._calibration_samples),
                "timestamp": time.time(),
            }
            with open(config.CALIBRATION_FILE, "w") as f:
                json.dump(cal, f, indent=2)

            logger.info(f"Calibration saved: avg_disp={avg_disp:.3f}, avg_vel={avg_vel:.3f}")
            logger.info(f"Recommended thresholds written to {config.CALIBRATION_FILE}")

        self._calibration_samples = []

    def _show_camera_error(self):
        """Show camera error window."""
        try:
            self._render_camera_error()
        except cv2.error:
            logger.error("Camera error (cannot display error window - headless?)")

    def _render_camera_error(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(frame, "CAMERA ERROR", (140, 220),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.putText(frame, "Please check camera permissions", (120, 260),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.putText(frame, "Press any key to exit", (180, 320),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
        cv2.imshow("AirShare Sender", frame)
        cv2.waitKey(5000)
        cv2.destroyAllWindows()

    def _cleanup(self):
        """Release all resources."""
        logger.info("Cleaning up...")
        self.camera.release()
        self.tracker.release()
        self.screenshot.release()
        self.network.stop_discovery()
        cv2.destroyAllWindows()
        logger.info("Cleanup complete")


def main():
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    sender = AirShareSender()
    sender.start()


if __name__ == "__main__":
    main()
