"""Hand tracking using MediaPipe Hands."""
import cv2
import logging
from typing import Optional

import mediapipe as mp
import numpy as np

from airshare import config
from airshare.shared.models import HandData

logger = logging.getLogger(__name__)


class HandTracker:
    """Detects and tracks hand landmarks using MediaPipe."""

    def __init__(self):
        self._hands: mp.solutions.hands.Hands | None = None
        self._drawing: mp.solutions.drawing_utils | None = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize MediaPipe Hands."""
        try:
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=config.MAX_HANDS,
                min_detection_confidence=config.MIN_DETECTION_CONFIDENCE,
                min_tracking_confidence=config.MIN_TRACKING_CONFIDENCE,
            )
            self._drawing = mp.solutions.drawing_utils
            self._initialized = True
            logger.info("MediaPipe Hands initialized")
            return True
        except Exception as e:
            logger.error(f"MediaPipe initialization error: {e}")
            return False

    def process(self, frame_rgb: np.ndarray) -> HandData:
        """Process an RGB frame and return hand data."""
        if not self._initialized or self._hands is None:
            return HandData(detected=False)

        results = self._hands.process(frame_rgb)

        if not results.multi_hand_landmarks:
            return HandData(detected=False)

        # Use the first (primary) hand
        hand_landmarks = results.multi_hand_landmarks[0]
        return self._extract_hand_data(hand_landmarks, frame_rgb.shape)

    def _extract_hand_data(self, landmarks, frame_shape) -> HandData:
        """Extract structured data from hand landmarks."""
        h, w = frame_shape[:2]

        # Convert landmarks to (x, y, z) tuples
        all_landmarks = []
        for lm in landmarks.landmark:
            all_landmarks.append((lm.x, lm.y, lm.z))

        # Key points
        wrist = (landmarks.landmark[0].x, landmarks.landmark[0].y)
        index_tip = (landmarks.landmark[8].x, landmarks.landmark[8].y)

        # Palm center: average of wrist(0), middle_mcp(9), index_mcp(5), ring_mcp(13), pinky_mcp(17)
        palm_indices = [0, 5, 9, 13, 17]
        palm_x = sum(landmarks.landmark[i].x for i in palm_indices) / len(palm_indices)
        palm_y = sum(landmarks.landmark[i].y for i in palm_indices) / len(palm_indices)

        # Bounding box in pixel coordinates
        xs = [int(lm.x * w) for lm in landmarks.landmark]
        ys = [int(lm.y * h) for lm in landmarks.landmark]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        pad = 10
        bbox = (
            max(0, x_min - pad),
            max(0, y_min - pad),
            min(w, x_max + pad) - max(0, x_min - pad),
            min(h, y_max + pad) - max(0, y_min - pad),
        )

        return HandData(
            detected=True,
            palm_center=(palm_x, palm_y),
            wrist=wrist,
            index_tip=index_tip,
            landmarks=all_landmarks,
            bbox=bbox,
        )

    def draw_landmarks(self, frame_bgr: np.ndarray, hand_data: HandData) -> np.ndarray:
        """Draw hand landmarks on a BGR frame for debug display."""
        if not hand_data.detected or not hand_data.landmarks:
            return frame_bgr

        h, w = frame_bgr.shape[:2]

        # Draw connections
        try:
            mp_drawing = mp.solutions.drawing_utils
            mp_hands = mp.solutions.hands
            # We need to reconstruct landmarks for drawing
            # Draw individual landmarks and connections manually
            connections = mp_hands.HAND_CONNECTIONS

            # Convert normalized landmarks back to pixel coordinates
            lm_list = []
            for (x, y, z) in hand_data.landmarks:
                lm = mp.solutions.landmarks.NormalizedLandmark()
                lm.x = x
                lm.y = y
                lm.z = z
                lm_list.append(lm)

            # Create a fake HandLandmark list
            fake_hand = mp.solutions.landmarks.NormalizedLandmarkList(landmark=lm_list)

            mp_drawing.draw_landmarks(
                frame_bgr, fake_hand, connections,
                mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=2),
                mp_drawing.DrawingSpec(color=(0, 200, 255), thickness=1),
            )
        except Exception:
            # Fallback: just draw circles at landmarks
            for (x, y, _) in hand_data.landmarks:
                px, py = int(x * w), int(y * h)
                cv2.circle(frame_bgr, (px, py), 4, (0, 255, 0), -1)

        # Draw palm center
        px = int(hand_data.palm_center[0] * w)
        py = int(hand_data.palm_center[1] * h)
        cv2.circle(frame_bgr, (px, py), 8, (0, 0, 255), -1)

        return frame_bgr

    def release(self):
        """Release MediaPipe resources."""
        if self._hands:
            self._hands.close()
            self._hands = None
        self._initialized = False
        logger.info("Hand tracker released")
