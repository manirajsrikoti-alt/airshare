"""Webcam capture using OpenCV."""
import cv2
import logging
import time

from airshare import config

logger = logging.getLogger(__name__)


class Camera:
    """Manages webcam capture."""

    def __init__(self, camera_index: int = config.CAMERA_INDEX):
        self.camera_index = camera_index
        self._cap: cv2.VideoCapture | None = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the camera. Returns True if successful."""
        try:
            self._cap = cv2.VideoCapture(self.camera_index)
            if not self._cap.isOpened():
                logger.error("Cannot open camera")
                return False

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
            self._cap.set(cv2.CAP_PROP_FPS, config.TARGET_FPS)

            # Verify we can read a frame
            ret, frame = self._cap.read()
            if not ret or frame is None:
                logger.error("Cannot read from camera")
                self.release()
                return False

            self._initialized = True
            logger.info(f"Camera initialized: index={self.camera_index}, "
                        f"resolution={frame.shape[1]}x{frame.shape[0]}")
            return True

        except Exception as e:
            logger.error(f"Camera initialization error: {e}")
            return False

    def read(self) -> tuple[bool, any]:
        """Read a frame from the camera. Returns (success, frame)."""
        if self._cap is None or not self._cap.isOpened():
            return False, None
        return self._cap.read()

    def get_frame_width(self) -> int:
        return int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self._cap else config.CAMERA_WIDTH

    def get_frame_height(self) -> int:
        return int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self._cap else config.CAMERA_HEIGHT

    def release(self):
        """Release camera resources."""
        if self._cap:
            self._cap.release()
            self._cap = None
        self._initialized = False
        logger.info("Camera released")

    @property
    def is_initialized(self) -> bool:
        return self._initialized
