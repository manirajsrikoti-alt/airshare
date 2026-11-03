"""Grab-and-fly overlay animations per docs/animation-spec.md.

Pure numpy/cv2 drawing; no camera or display dependencies. All timings come
from airshare.config (millisecond spec constants) so they stay tunable.
"""
import cv2
import numpy as np
import time

from airshare import config

_BORDER_COLOR = (255, 255, 255)


def _ease_out_cubic(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1.0 - (1.0 - x) ** 3


def _cubic_bezier(x1, y1, x2, y2):
    """Return f(t) -> y for cubic-bezier(x1, y1, x2, y2) via Newton iteration."""
    def bezier(t, a, b):
        # one-dimensional cubic bezier with endpoints 0 and 1
        return 3 * a * t * (1 - t) ** 2 + 3 * b * t ** 2 * (1 - t) + t ** 3

    def f(x):
        t = x
        for _ in range(8):
            err = bezier(t, x1, x2) - x
            if abs(err) < 1e-4:
                break
            deriv = (3 * x1 * (1 - t) ** 2
                     + 6 * (x2 - x1) * t * (1 - t)
                     + 3 * (1 - x2) * t ** 2)
            if abs(deriv) < 1e-6:
                break
            t -= err / deriv
        return bezier(t, y1, y2)

    return f


class AnimationPlayer:
    """Plays the sender-side grab/fly/ripple animation sequences."""

    def __init__(self):
        self._sequence = None      # "grab" | "fly" | "ripple" | None
        self._t0 = 0.0
        self._grab_center = None
        self._frozen_frame = None
        self._fly_thumb = None
        self._fly_edge = "right"
        self._fly_ease = _cubic_bezier(*config.FLY_EASING)

    # --- Public API (spec interface) ---

    def start_grab(self, center: tuple, t0: float = None):
        """Begin the grab sequence: freeze -> flash/shrink -> hold."""
        self._sequence = "grab"
        self._t0 = time.time() if t0 is None else t0
        self._grab_center = center
        self._frozen_frame = None

    def start_fly(self, thumbnail: np.ndarray, edge: str = "right",
                  t0: float = None):
        """Begin the fly-off sequence with a captured thumbnail."""
        self._sequence = "fly"
        self._t0 = time.time() if t0 is None else t0
        self._fly_thumb = thumbnail
        self._fly_edge = edge

    def start_ripple(self, t0: float = None):
        """Begin the arrival ripple (expanding halo ring)."""
        self._sequence = "ripple"
        self._t0 = time.time() if t0 is None else t0

    def is_playing(self, t: float = None) -> bool:
        if self._sequence is None:
            return False
        t = time.time() if t is None else t
        return self.phase_at(t) != "idle"

    def phase_at(self, t: float) -> str:
        """Current animation phase at time t (seconds)."""
        if self._sequence is None:
            return "idle"
        elapsed_ms = (t - self._t0) * 1000.0
        if elapsed_ms < 0:
            return "idle"
        if self._sequence == "grab":
            if elapsed_ms < config.GRAB_FREEZE_MS:
                return "freeze"
            if elapsed_ms < config.GRAB_FREEZE_MS + config.SHRINK_MS:
                return "shrink"
            if elapsed_ms < (config.GRAB_FREEZE_MS + config.SHRINK_MS
                             + config.HOLD_MS):
                return "hold"
            return "idle"
        if self._sequence == "fly":
            return "fly" if elapsed_ms < config.FLY_MS else "idle"
        if self._sequence == "ripple":
            return "ripple" if elapsed_ms < config.RIPPLE_MS else "idle"
        return "idle"

    def fly_position(self, t: float, width: int, height: int) -> tuple:
        """Thumbnail center at time t along the dwell -> edge arc path."""
        dwell_x = self._dwell_x(width)
        dwell_y = self._dwell_y(height)
        if self._sequence != "fly":
            return (dwell_x, dwell_y)
        elapsed_ms = (t - self._t0) * 1000.0
        x_norm = min(max(elapsed_ms / config.FLY_MS, 0.0), 1.0)
        p = self._fly_ease(x_norm)
        target_x = width if self._fly_edge == "right" else 0
        x = dwell_x + (target_x - dwell_x) * p
        # slight upward arc (~10% of height), peaks mid-flight
        arc = config.FLY_ARC_PCT * height * 4.0 * x_norm * (1.0 - x_norm)
        y = dwell_y - arc
        return (x, y)

    def draw(self, frame: np.ndarray, t: float) -> np.ndarray:
        """Render the active animation phase onto frame; returns the frame."""
        phase = self.phase_at(t)
        if phase == "idle":
            return frame

        h, w = frame.shape[:2]

        if phase == "freeze":
            if self._frozen_frame is None:
                self._frozen_frame = frame.copy()
            frame[:] = self._frozen_frame
            self._draw_border(frame, (0, 0, w, h), radius=0)
        elif phase == "shrink":
            if self._frozen_frame is None:
                self._frozen_frame = frame.copy()
            frame[:] = self._frozen_frame
            elapsed_ms = (t - self._t0) * 1000.0
            shrink_p = _ease_out_cubic(
                (elapsed_ms - config.GRAB_FREEZE_MS) / config.SHRINK_MS)
            scale = (config.THUMB_SCALE_START
                     + (config.THUMB_SCALE_END - config.THUMB_SCALE_START)
                     * shrink_p)
            self._draw_thumbnail(frame, self._frozen_frame, scale, shrink_p)
            # white flash spikes then fades over FLASH_MS, overlapping shrink
            flash_t = (elapsed_ms - config.GRAB_FREEZE_MS) / config.FLASH_MS
            if flash_t < 1.0:
                alpha = 0.9 * (1.0 - flash_t)
                cv2.addWeighted(frame, 1.0 - alpha,
                                np.full_like(frame, 255), alpha, 0, frame)
        elif phase == "hold":
            self._draw_thumbnail(frame, self._frozen_frame,
                                 config.THUMB_SCALE_END, 1.0)
        elif phase == "fly" and self._fly_thumb is not None:
            cx, cy = self.fly_position(t, w, h)
            elapsed_ms = (t - self._t0) * 1000.0
            fade_start = config.FLY_MS - 100.0
            alpha = 1.0 if elapsed_ms < fade_start else max(
                0.0, (config.FLY_MS - elapsed_ms) / 100.0)
            self._stamp(frame, self._fly_thumb, int(cx), int(cy), alpha)
        elif phase == "ripple":
            elapsed_ms = (t - self._t0) * 1000.0
            p = _ease_out_cubic(elapsed_ms / config.RIPPLE_MS)
            radius = int(p * min(w, h) * 0.5)
            alpha = 1.0 - p
            if radius > 0 and alpha > 0:
                overlay = frame.copy()
                cv2.circle(overlay, (0, h // 2), radius,
                           _BORDER_COLOR, 3, cv2.LINE_AA)
                cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
        return frame

    # --- Internal helpers ---

    def _dwell_x(self, width: int) -> float:
        return config.THUMB_SCALE_END * width / 2 + 16

    def _dwell_y(self, height: int) -> float:
        return height - config.THUMB_SCALE_END * height / 2 - 16

    def _draw_border(self, frame, rect, radius=0, thickness=None):
        x, y, w, h = rect
        thickness = thickness or config.THUMB_BORDER_PX
        if radius > 0:
            cv2.rectangle(frame, (x, y), (x + w, y + h),
                          _BORDER_COLOR, thickness, cv2.LINE_AA)
        else:
            cv2.rectangle(frame, (x, y), (x + w - 1, y + h - 1),
                          _BORDER_COLOR, thickness)

    def _draw_thumbnail(self, frame, source, scale, pos_p):
        """Draw the shrinking/resting thumbnail; pos_p interpolates center->dwell."""
        if source is None:
            return
        fh, fw = frame.shape[:2]
        tw = max(1, int(fw * scale))
        th = max(1, int(fh * scale))
        thumb = cv2.resize(source, (tw, th), interpolation=cv2.INTER_AREA)
        start_cx, start_cy = fw // 2, fh // 2
        dwell_cx = int(self._dwell_x(fw))
        dwell_cy = int(self._dwell_y(fh))
        cx = int(start_cx + (dwell_cx - start_cx) * pos_p)
        cy = int(start_cy + (dwell_cy - start_cy) * pos_p)
        self._stamp(frame, thumb, cx, cy, 1.0)

    def _stamp(self, frame, thumb, cx, cy, alpha):
        """Paste thumb centered at (cx, cy) with white border, clipped to frame."""
        if alpha <= 0:
            return
        fh, fw = frame.shape[:2]
        th, tw = thumb.shape[:2]
        x0, y0 = cx - tw // 2, cy - th // 2
        x1, y1 = x0 + tw, y0 + th
        fx0, fy0 = max(0, x0), max(0, y0)
        fx1, fy1 = min(fw, x1), min(fh, y1)
        if fx1 <= fx0 or fy1 <= fy0:
            return
        sub = thumb[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
        region = frame[fy0:fy1, fx0:fx1]
        if alpha >= 1.0:
            region[:] = sub
        else:
            cv2.addWeighted(sub, alpha, region, 1.0 - alpha, 0, region)
        b = config.THUMB_BORDER_PX
        cv2.rectangle(frame, (fx0, fy0), (fx1 - 1, fy1 - 1),
                      _BORDER_COLOR, b, cv2.LINE_AA)
