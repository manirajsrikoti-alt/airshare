"""Data models shared between sender and receiver."""
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Tuple
import time


class SenderState(Enum):
    """Sender application states."""
    IDLE = auto()
    READY = auto()
    GESTURE_ARMED = auto()
    CAPTURE_DETECTED = auto()
    CAPTURING = auto()
    CAPTURED = auto()
    READY_TO_TRANSFER = auto()
    TRANSFER_DETECTED = auto()
    SENDING = auto()
    TRANSFER_SUCCESS = auto()
    TRANSFER_FAILED = auto()
    CANCELLED = auto()
    COOLDOWN = auto()
    CALIBRATING = auto()
    CAMERA_ERROR = auto()


class GestureType(Enum):
    """Detected gesture types (Huawei-style set)."""
    NONE = auto()
    GRAB = auto()       # open -> fist grab, held
    FLICK = auto()      # fast horizontal palm movement
    CANCEL = auto()     # open palm held still


@dataclass
class HandData:
    """Processed hand landmark data for a single frame."""
    detected: bool = False
    palm_center: Tuple[float, float] = (0.5, 0.5)
    wrist: Tuple[float, float] = (0.5, 0.5)
    index_tip: Tuple[float, float] = (0.5, 0.5)
    is_fist: bool = False
    landmarks: list = field(default_factory=list)  # 21 landmarks as (x, y, z)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h in pixels
    timestamp: float = field(default_factory=time.time)


@dataclass
class MovementFrame:
    """A single frame in the movement history."""
    palm_x: float = 0.0
    palm_y: float = 0.0
    wrist_x: float = 0.0
    wrist_y: float = 0.0
    timestamp: float = 0.0

    @property
    def position(self) -> Tuple[float, float]:
        return (self.palm_x, self.palm_y)


@dataclass
class GestureResult:
    """Result of gesture recognition for a frame."""
    gesture: GestureType = GestureType.NONE
    confidence: float = 0.0
    displacement: float = 0.0
    velocity: float = 0.0
    direction: str = "none"
    frame_count: int = 0

    @property
    def detected(self) -> bool:
        return self.gesture != GestureType.NONE


@dataclass
class CalibrationData:
    """Calibration statistics for gestures."""
    sample_count: int = 0
    timestamp: float = 0.0


@dataclass
class TransferInfo:
    """Information about a file transfer."""
    filename: str = ""
    sender: str = ""
    timestamp: float = 0.0
    success: bool = False
    error: str = ""
    file_path: str = ""
