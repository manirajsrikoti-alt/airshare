"""Tests for the sender-side animation player (pure logic, no camera)."""
import numpy as np
import pytest

from airshare import config
from airshare.sender.animations import AnimationPlayer


W, H = 640, 480


def make_frame(value=40):
    frame = np.full((H, W, 3), value, dtype=np.uint8)
    return frame


def ms(s):
    return s / 1000.0


class TestGrabSequenceTiming:
    """Phase sequence: freeze -> flash/shrink -> hold, durations from spec."""

    def test_freeze_phase_duration(self):
        p = AnimationPlayer()
        p.start_grab(center=(W // 2, H // 2), t0=0.0)
        # During GRAB_FREEZE_MS we are in the freeze phase
        assert p.phase_at(ms(config.GRAB_FREEZE_MS) / 2) == "freeze"
        # Just before freeze ends, still freeze
        assert p.phase_at(ms(config.GRAB_FREEZE_MS) - 0.001) == "freeze"

    def test_shrink_phase_after_freeze(self):
        p = AnimationPlayer()
        p.start_grab(center=(W // 2, H // 2), t0=0.0)
        t = ms(config.GRAB_FREEZE_MS) + ms(config.SHRINK_MS) / 2
        assert p.phase_at(t) == "shrink"

    def test_hold_phase_after_shrink(self):
        p = AnimationPlayer()
        p.start_grab(center=(W // 2, H // 2), t0=0.0)
        t = ms(config.GRAB_FREEZE_MS + config.SHRINK_MS) + ms(config.HOLD_MS) / 2
        assert p.phase_at(t) == "hold"

    def test_done_after_full_sequence(self):
        p = AnimationPlayer()
        p.start_grab(center=(W // 2, H // 2), t0=0.0)
        total = ms(config.GRAB_FREEZE_MS + config.SHRINK_MS + config.HOLD_MS)
        assert p.phase_at(total + 0.01) == "idle"
        assert not p.is_playing(total + 0.01)

    def test_is_playing_during_sequence(self):
        p = AnimationPlayer()
        p.start_grab(center=(W // 2, H // 2), t0=0.0)
        assert p.is_playing(0.0)
        assert p.is_playing(ms(config.GRAB_FREEZE_MS + config.SHRINK_MS))


class TestFlySequence:
    def test_fly_duration_from_spec(self):
        p = AnimationPlayer()
        thumb = np.full((60, 100, 3), 200, dtype=np.uint8)
        p.start_fly(thumb, edge="right", t0=1.0)
        assert p.phase_at(1.0 + ms(config.FLY_MS) / 2) == "fly"
        assert p.is_playing(1.0 + ms(config.FLY_MS) / 2)
        assert not p.is_playing(1.0 + ms(config.FLY_MS) + 0.01)
        assert p.phase_at(1.0 + ms(config.FLY_MS) + 0.01) == "idle"

    def test_fly_position_moves_toward_edge(self):
        p = AnimationPlayer()
        thumb = np.full((60, 100, 3), 200, dtype=np.uint8)
        p.start_fly(thumb, edge="right", t0=0.0)
        x_start, _ = p.fly_position(0.0, W, H)
        x_mid, _ = p.fly_position(ms(config.FLY_MS) / 2, W, H)
        x_end, _ = p.fly_position(ms(config.FLY_MS), W, H)
        assert x_start < x_mid < x_end

    def test_fly_easing_is_ease_in(self):
        """Ease-in (accelerating): second half covers more distance."""
        p = AnimationPlayer()
        thumb = np.full((60, 100, 3), 200, dtype=np.uint8)
        p.start_fly(thumb, edge="right", t0=0.0)
        d = ms(config.FLY_MS)
        x0, _ = p.fly_position(0.0, W, H)
        x1, _ = p.fly_position(d * 0.25, W, H)
        x2, _ = p.fly_position(d * 0.5, W, H)
        x3, _ = p.fly_position(d * 0.75, W, H)
        first_quarter = x1 - x0
        third_quarter = x3 - x2
        assert third_quarter > first_quarter


class TestRipple:
    def test_ripple_duration_from_spec(self):
        p = AnimationPlayer()
        p.start_ripple(t0=2.0)
        assert p.is_playing(2.0 + ms(config.RIPPLE_MS) / 2)
        assert not p.is_playing(2.0 + ms(config.RIPPLE_MS) + 0.01)


class TestDraw:
    def test_draw_returns_same_shape(self):
        p = AnimationPlayer()
        frame = make_frame()
        p.start_grab(center=(W // 2, H // 2), t0=0.0)
        for t in (0.0, 0.2, 0.45, 0.55, 0.7, 0.9):
            out = p.draw(frame.copy(), t)
            assert out.shape == frame.shape
            assert out.dtype == np.uint8

    def test_draw_freeze_shows_frozen_frame_with_border(self):
        p = AnimationPlayer()
        frame = make_frame(value=30)
        p.start_grab(center=(W // 2, H // 2), t0=0.0)
        p.draw(frame.copy(), 0.0)  # captures the frozen frame
        out = p.draw(make_frame(value=200), ms(config.GRAB_FREEZE_MS) / 2)
        # Interior shows the frozen (dark) frame, not the new bright frame
        assert out[H // 2, W // 2].mean() < 100
        # White border present at top-left corner region
        assert out[2, 2].mean() > 200

    def test_draw_fly_returns_same_shape(self):
        p = AnimationPlayer()
        thumb = np.full((60, 100, 3), 200, dtype=np.uint8)
        p.start_fly(thumb, edge="right", t0=0.0)
        out = p.draw(make_frame(), ms(config.FLY_MS) / 2)
        assert out.shape == (H, W, 3)

    def test_draw_idle_is_passthrough(self):
        p = AnimationPlayer()
        frame = make_frame()
        out = p.draw(frame.copy(), 5.0)
        assert np.array_equal(out, frame)
