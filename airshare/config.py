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

# --- Gesture Thresholds (Huawei-style: fist-grab, flick, palm-cancel) ---
GRAB_HOLD_FRAMES = 8                  # fist must be held this many frames for GRAB
CANCEL_HOLD_FRAMES = 20               # open palm held this many frames for CANCEL

# Flick gesture (fast horizontal palm movement)
FLICK_MIN_FRAME_DISPLACEMENT = 0.04   # min per-frame horizontal delta (normalized)
FLICK_MIN_TOTAL_DISPLACEMENT = 0.10   # min total horizontal travel (normalized)
FLICK_WINDOW_FRAMES = 5               # frames analyzed for flick velocity

# Movement below this per-frame delta counts as "held still" for CANCEL
CANCEL_MAX_FRAME_DISPLACEMENT = 0.01

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
