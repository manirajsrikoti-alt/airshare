"""Tests for receiver file storage."""
import os
import io
import pytest
import sys
import tempfile
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from airshare.receiver.storage import StorageManager


def make_test_image(width=100, height=100, color=(255, 0, 0)) -> bytes:
    """Create a test PNG image and return as bytes."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestStorageManager:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = StorageManager(upload_dir=self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_store_file(self):
        """Can store and retrieve a file."""
        data = make_test_image()
        metadata = self.storage.store_file(data, "test.png", "TestSender")
        assert metadata["sender"] == "TestSender"
        assert metadata["filename"].startswith("airshare_")
        assert metadata["size"] == len(data)
        assert os.path.exists(metadata["file_path"])

    def test_validate_valid_image(self):
        """Valid image passes validation."""
        data = make_test_image()
        valid, err = self.storage.validate_file(data, "test.png")
        assert valid
        assert err == ""

    def test_validate_empty_file(self):
        """Empty file is rejected."""
        valid, err = self.storage.validate_file(b"", "test.png")
        assert not valid
        assert "Empty" in err

    def test_validate_too_large(self):
        """Oversized file is rejected."""
        data = b"x" * (50 * 1024 * 1024 + 1)  # 50MB + 1
        valid, err = self.storage.validate_file(data, "big.png")
        assert not valid
        assert "too large" in err.lower()

    def test_validate_bad_extension(self):
        """Executable extension is rejected."""
        data = make_test_image()
        valid, err = self.storage.validate_file(data, "virus.exe")
        assert not valid
        assert "not allowed" in err.lower() or "dangerous" in err.lower()

    def test_validate_invalid_image_data(self):
        """Corrupt image data is rejected."""
        valid, err = self.storage.validate_file(b"not an image", "test.png")
        assert not valid
        assert "invalid" in err.lower()

    def test_safe_filename(self):
        """Generated filenames are safe."""
        name = self.storage.generate_safe_filename("Test@Sender!")
        assert name.startswith("airshare_Test_Sender_")
        assert name.endswith(".png")
        # No dangerous characters
        assert "/" not in name
        assert ".." not in name

    def test_latest_file(self):
        """Tracks latest file."""
        assert self.storage.latest_file is None
        data = make_test_image()
        self.storage.store_file(data, "a.png", "A")
        assert self.storage.latest_file is not None

    def test_list_files(self):
        """Lists stored files."""
        data = make_test_image()
        self.storage.store_file(data, "a.png", "A")
        self.storage.store_file(data, "b.png", "B")
        files = self.storage.list_files()
        assert len(files) == 2

    def test_recent_files(self):
        """Returns recent transfer log."""
        data = make_test_image()
        self.storage.store_file(data, "a.png", "A")
        recent = self.storage.get_recent_files(5)
        assert len(recent) == 1
        assert recent[0]["sender"] == "A"
