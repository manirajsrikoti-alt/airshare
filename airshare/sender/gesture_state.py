"""State machine for the gesture-driven interaction flow."""
import time
import logging

from airshare.shared.models import SenderState

logger = logging.getLogger(__name__)

# Valid state transitions
_TRANSITIONS = {
    SenderState.IDLE: {SenderState.READY, SenderState.CAMERA_ERROR},
    SenderState.READY: {
        SenderState.GESTURE_ARMED,
        SenderState.CAPTURE_DETECTED,
        SenderState.CALIBRATING,
    },
    SenderState.GESTURE_ARMED: {
        SenderState.CAPTURE_DETECTED,
        SenderState.READY,  # arm cancelled
    },
    SenderState.CAPTURE_DETECTED: {SenderState.CAPTURING},
    SenderState.CAPTURING: {SenderState.CAPTURED, SenderState.TRANSFER_FAILED},
    SenderState.CAPTURED: {SenderState.READY_TO_TRANSFER},
    SenderState.READY_TO_TRANSFER: {
        SenderState.TRANSFER_DETECTED,
        SenderState.CAPTURE_DETECTED,  # re-capture
        SenderState.READY,  # cancel / timeout
    },
    SenderState.TRANSFER_DETECTED: {SenderState.SENDING, SenderState.TRANSFER_FAILED},
    SenderState.SENDING: {
        SenderState.TRANSFER_SUCCESS,
        SenderState.TRANSFER_FAILED,
    },
    SenderState.TRANSFER_SUCCESS: {SenderState.READY, SenderState.COOLDOWN},
    SenderState.TRANSFER_FAILED: {
        SenderState.READY_TO_TRANSFER,
        SenderState.READY,
    },
    SenderState.COOLDOWN: {SenderState.READY},
    SenderState.CALIBRATING: {SenderState.READY},
    SenderState.CAMERA_ERROR: {SenderState.IDLE},
}


class GestureStateMachine:
    """Manages the application state based on gesture events."""

    def __init__(self):
        self._state = SenderState.IDLE
        self._state_entered_at = time.time()
        self._previous_state = SenderState.IDLE
        self._listeners: list = []

    @property
    def state(self) -> SenderState:
        return self._state

    @property
    def previous_state(self) -> SenderState:
        return self._previous_state

    @property
    def time_in_state(self) -> float:
        return time.time() - self._state_entered_at

    def transition(self, new_state: SenderState) -> bool:
        """Attempt a state transition. Returns True if successful."""
        valid = _TRANSITIONS.get(self._state, set())
        if new_state not in valid:
            logger.debug(f"Invalid transition: {self._state.name} -> {new_state.name}")
            return False

        old_state = self._state
        self._previous_state = old_state
        self._state = new_state
        self._state_entered_at = time.time()

        logger.info(f"State: {old_state.name} -> {new_state.name}")
        for listener in self._listeners:
            try:
                listener(old_state, new_state)
            except Exception as e:
                logger.error(f"State listener error: {e}")

        return True

    def force_state(self, new_state: SenderState):
        """Force a state transition (for error recovery)."""
        old = self._state
        self._previous_state = old
        self._state = new_state
        self._state_entered_at = time.time()
        logger.warning(f"Forced state: {old.name} -> {new_state.name}")

    def on_transition(self, callback):
        """Register a state transition listener."""
        self._listeners.append(callback)

    def ready_for_new_action(self) -> bool:
        """Check if we're in a state where a new gesture can start."""
        return self._state in {
            SenderState.READY,
            SenderState.READY_TO_TRANSFER,
        }

    def is_capturing(self) -> bool:
        return self._state in {
            SenderState.CAPTURE_DETECTED,
            SenderState.CAPTURING,
            SenderState.CAPTURED,
        }

    def is_sending(self) -> bool:
        return self._state in {
            SenderState.TRANSFER_DETECTED,
            SenderState.SENDING,
        }
