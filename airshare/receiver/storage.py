"""Secure file storage for received screenshots."""
import os
import time
import uuid
import logging
from typing import Optional, List
from PIL import Image
import io

from airshare import config

logger = logging.getLogger(__name__)


class StorageManager:
    """Handles secure storage and retrieval of received files."""

    def __init__(self, upload_dir: Optional[str] = None):
        self.upload_dir = upload_dir or config.RECEIVER_UPLOAD_DIR
        os.makedirs(self.upload_dir, exist_ok=True)
        self._latest_file: Optional[str] = None
        self._transfer_log: List[dict] = []

    def validate_file(self, data: bytes, filename: str) -> tuple[bool, str]:
        """Validate uploaded file data. Returns (is_valid, error_message)."""
        # Check file size
        if len(data) > config.MAX_UPLOAD_SIZE:
            return False, f"File too large: {len(data)} bytes (max {config.MAX_UPLOAD_SIZE})"

        if len(data) == 0:
            return False, "Empty file"

        # Check extension (from original filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in config.ALLOWED_EXTENSIONS:
            return False, f"File type not allowed: {ext}"

        # Check for executable extensions hidden in the data
        dangerous_exts = {".exe", ".bat", ".cmd", ".sh", ".ps1", ".dll", ".msi", ".com", ".scr"}
        if ext in dangerous_exts:
            return False, f"Dangerous file type rejected: {ext}"

        # Verify image can be opened
        try:
            img = Image.open(io.BytesIO(data))
            img.verify()
        except Exception as e:
            return False, f"Invalid image data: {e}"

        return True, ""

    def generate_safe_filename(self, sender_name: str = "unknown") -> str:
        """Generate a safe, unique filename for storage."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:8]
        safe_sender = "".join(c if c.isalnum() else "_" for c in sender_name)[:20]
        return f"airshare_{safe_sender}_{timestamp}_{short_id}.png"

    def store_file(self, data: bytes, original_filename: str,
                   sender_name: str = "unknown") -> dict:
        """Store a validated file. Returns metadata dict."""
        safe_name = self.generate_safe_filename(sender_name)
        file_path = os.path.join(self.upload_dir, safe_name)

        with open(file_path, "wb") as f:
            f.write(data)

        self._latest_file = file_path
        metadata = {
            "filename": safe_name,
            "original_filename": original_filename,
            "sender": sender_name,
            "size": len(data),
            "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "file_path": file_path,
        }
        self._transfer_log.append(metadata)
        logger.info(f"Stored file: {safe_name} ({len(data)} bytes) from {sender_name}")
        return metadata

    @property
    def latest_file(self) -> Optional[str]:
        """Path to the most recently received file."""
        return self._latest_file

    @property
    def latest_filename(self) -> Optional[str]:
        """Filename of the most recently received file."""
        if self._latest_file:
            return os.path.basename(self._latest_file)
        return None

    def get_recent_files(self, limit: int = 10) -> List[dict]:
        """Get the most recent transfer records."""
        return list(reversed(self._transfer_log[-limit:]))

    def list_files(self) -> List[str]:
        """List all stored files."""
        files = []
        for f in sorted(os.listdir(self.upload_dir)):
            if os.path.isfile(os.path.join(self.upload_dir, f)):
                files.append(f)
        return files
