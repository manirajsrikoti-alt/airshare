"""Screenshot capture using MSS."""
import os
import time
import logging
from typing import Optional

import mss
from PIL import Image

from airshare import config

logger = logging.getLogger(__name__)


class ScreenshotCapture:
    """Captures screenshots of the primary display."""

    def __init__(self):
        self._sct: mss.mss | None = None
        self._latest_screenshot: Optional[str] = None

    def initialize(self) -> bool:
        """Initialize MSS."""
        try:
            self._sct = mss.mss()
            monitors = self._sct.monitors
            logger.info(f"MSS initialized. Available monitors: {len(monitors) - 1}")
            return True
        except Exception as e:
            logger.error(f"MSS initialization error: {e}")
            return False

    def capture(self) -> Optional[str]:
        """Capture the primary display. Returns the path to the saved screenshot."""
        if self._sct is None:
            logger.error("MSS not initialized")
            return None

        try:
            # Monitor index 1 is the primary display (index 0 is "all monitors combined")
            monitor = self._sct.monitors[1]

            # Capture
            sct_img = self._sct.grab(monitor)

            # Convert to PIL Image
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            # Generate filename
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            millis = int(time.time() * 1000) % 1000
            filename = f"capture_{timestamp}_{millis:03d}.png"
            os.makedirs(config.SCREENSHOT_DIR, exist_ok=True)
            filepath = os.path.join(config.SCREENSHOT_DIR, filename)

            # Save
            img.save(filepath, "PNG")
            self._latest_screenshot = filepath

            logger.info(f"Screenshot captured: {filename}")
            return filepath

        except Exception as e:
            logger.error(f"Screenshot capture error: {e}")
            return None

    @property
    def latest_screenshot(self) -> Optional[str]:
        return self._latest_screenshot

    @property
    def has_screenshot(self) -> bool:
        return self._latest_screenshot is not None and os.path.exists(self._latest_screenshot)

    def get_screenshot_data(self) -> Optional[tuple[bytes, str]]:
        """Read the latest screenshot and return (file_bytes, filename)."""
        if not self.has_screenshot:
            return None
        try:
            with open(self._latest_screenshot, "rb") as f:
                data = f.read()
            return data, os.path.basename(self._latest_screenshot)
        except Exception as e:
            logger.error(f"Error reading screenshot: {e}")
            return None

    def release(self):
        """Release MSS resources."""
        if self._sct:
            self._sct.close()
            self._sct = None
        logger.info("Screenshot capture released")
