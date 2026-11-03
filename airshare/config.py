"""Global configuration for AirShare."""
import os

# --- General ---
APP_NAME = "AirShare"
VERSION = "1.0.0"
DEBUG_MODE = os.getenv("AIRSHARE_DEBUG", "0") == "1"

# --- Receiver ---
RECEIVER_HOST = "0.0.0.0"
RECEIVER_PORT = int(os.getenv("AIRSHARE_PORT", "5077"))  # avoid AirPlay's 5000
RECEIVER_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "receiver", "received")
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

# --- Discovery (UDP broadcast) ---
DISCOVERY_PORT = 5001
DISCOVERY_MESSAGE = "AIRSHARE_RECEIVER"
DISCOVERY_INTERVAL = 2  # seconds between broadcasts

# --- Sender ---
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
CAMERA_INDEX = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
TARGET_FPS = 30

# --- Hand Tracking ---
MAX_HANDS = 1
MIN_DETECTION_CONFIDENCE = 0.6
MIN_TRACKING_CONFIDENCE = 0.6

# --- Gesture Thresholds ---
# Capture gesture (upward push)
CAPTURE_MIN_DISPLACEMENT = 0.08       # minimum palm displacement (normalized)
CAPTURE_MIN_VELOCITY = 0.15           # minimum velocity
CAPTURE_MIN_FRAMES = 6                # minimum frames for gesture
CAPTURE_MAX_FRAMES = 40               # maximum frames (prevent slow drift)
CAPTURE_MIN_DIRECTION_RATIO = 0.6     # at least 60% of movement must be upward
CAPTURE_VELOCITY_RATIO = 0.5          # vertical velocity / total velocity

# Transfer gesture (horizontal throw)
TRANSFER_MIN_DISPLACEMENT = 0.10
TRANSFER_MIN_VELOCITY = 0.18
TRANSFER_MIN_FRAMES = 6
TRANSFER_MAX_FRAMES = 40
TRANSFER_MIN_DIRECTION_RATIO = 0.6    # at least 60% must be horizontal
TRANSFER_VELOCITY_RATIO = 0.5

# --- State Machine ---
COOLDOWN_SECONDS = 1.5
HAND_LOST_GRACE_MS = 400

# --- Movement History ---
MOVEMENT_HISTORY_LENGTH = 30

# --- Network ---
TRANSFER_TIMEOUT = 30  # seconds
HTTP_TIMEOUT = 15

# --- Paths ---
CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), ".calibration.json")

# Ensure directories exist
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(RECEIVER_UPLOAD_DIR, exist_ok=True)
