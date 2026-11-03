"""Tests for the gesture state machine."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from airshare.shared.models import SenderState
from airshare.sender.gesture_state import GestureStateMachine


class TestGestureStateMachine:

    def setup_method(self):
        self.sm = GestureStateMachine()

    def test_initial_state(self):
        assert self.sm.state == SenderState.IDLE

    def test_valid_transitions(self):
        """Test normal happy path transitions."""
        assert self.sm.transition(SenderState.READY)
        assert self.sm.state == SenderState.READY

        assert self.sm.transition(SenderState.GESTURE_ARMED)
        assert self.sm.state == SenderState.GESTURE_ARMED

        assert self.sm.transition(SenderState.CAPTURE_DETECTED)
        assert self.sm.state == SenderState.CAPTURE_DETECTED

        assert self.sm.transition(SenderState.CAPTURING)
        assert self.sm.state == SenderState.CAPTURING

        assert self.sm.transition(SenderState.CAPTURED)
        assert self.sm.state == SenderState.CAPTURED

        assert self.sm.transition(SenderState.READY_TO_TRANSFER)
        assert self.sm.state == SenderState.READY_TO_TRANSFER

        assert self.sm.transition(SenderState.TRANSFER_DETECTED)
        assert self.sm.state == SenderState.TRANSFER_DETECTED

        assert self.sm.transition(SenderState.SENDING)
        assert self.sm.state == SenderState.SENDING

        assert self.sm.transition(SenderState.TRANSFER_SUCCESS)
        assert self.sm.state == SenderState.TRANSFER_SUCCESS

        assert self.sm.transition(SenderState.READY)
        assert self.sm.state == SenderState.READY

    def test_invalid_transition(self):
        """Cannot skip states."""
        assert not self.sm.transition(SenderState.CAPTURING)
        assert self.sm.state == SenderState.IDLE  # unchanged

    def test_force_state(self):
        """Force can set any state."""
        self.sm.force_state(SenderState.TRANSFER_SUCCESS)
        assert self.sm.state == SenderState.TRANSFER_SUCCESS

    def test_previous_state(self):
        """Tracks previous state."""
        self.sm.force_state(SenderState.READY)
        self.sm.transition(SenderState.GESTURE_ARMED)
        assert self.sm.previous_state == SenderState.READY

    def test_ready_for_new_action(self):
        """Can start gesture from READY and READY_TO_TRANSFER."""
        self.sm.force_state(SenderState.READY)
        assert self.sm.ready_for_new_action()

        self.sm.force_state(SenderState.READY_TO_TRANSFER)
        assert self.sm.ready_for_new_action()

        self.sm.force_state(SenderState.SENDING)
        assert not self.sm.ready_for_new_action()

    def test_is_capturing(self):
        """Detects capturing states."""
        for s in [SenderState.CAPTURE_DETECTED, SenderState.CAPTURING, SenderState.CAPTURED]:
            self.sm.force_state(s)
            assert self.sm.is_capturing()

    def test_is_sending(self):
        """Detects sending states."""
        for s in [SenderState.TRANSFER_DETECTED, SenderState.SENDING]:
            self.sm.force_state(s)
            assert self.sm.is_sending()

    def test_listener_called(self):
        """State change listeners are called."""
        transitions = []
        self.sm.on_transition(lambda old, new: transitions.append((old, new)))
        self.sm.force_state(SenderState.READY)
        self.sm.transition(SenderState.GESTURE_ARMED)
        assert len(transitions) == 1
        assert transitions[0] == (SenderState.READY, SenderState.GESTURE_ARMED)

    def test_time_in_state(self):
        """Tracks time spent in state."""
        self.sm.force_state(SenderState.READY)
        import time
        time.sleep(0.05)
        assert self.sm.time_in_state >= 0.04

    def test_recapture_from_transfer_ready(self):
        """Can re-capture from READY_TO_TRANSFER."""
        self.sm.force_state(SenderState.READY_TO_TRANSFER)
        assert self.sm.transition(SenderState.CAPTURE_DETECTED)
        assert self.sm.state == SenderState.CAPTURE_DETECTED
