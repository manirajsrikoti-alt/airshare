"""Persistent store of paired peers and their auth tokens."""
import json
import os
import secrets
import tempfile
import threading

DEFAULT_STORE_PATH = os.path.expanduser(os.path.join("~", ".airshare", "peers.json"))


def generate_pin() -> str:
    """Generate a 6-digit pairing PIN."""
    return f"{secrets.randbelow(1000000):06d}"


def generate_token() -> str:
    """Generate a random per-peer auth token."""
    return secrets.token_hex(16)


class PairingStore:
    """JSON-backed store of paired peers, written with mode 600."""

    def __init__(self, path: str = DEFAULT_STORE_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._peers: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._peers = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._peers = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # Write to a temp file in the same directory, then atomically replace
        # so a concurrent reader never sees a truncated file.
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(self.path) or ".", prefix=".peers-", suffix=".tmp",
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._peers, f, indent=2)
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_token(self, peer_id: str) -> str | None:
        """Return the stored token for a peer, or None."""
        with self._lock:
            peer = self._peers.get(peer_id)
            return peer["token"] if peer else None

    def add_peer(self, peer_id: str, name: str, token: str) -> None:
        """Add or replace a paired peer."""
        with self._lock:
            self._peers[peer_id] = {"name": name, "token": token}
            self._save()

    def list_peers(self) -> list[dict]:
        """List all paired peers as dicts with peer_id, name, token."""
        with self._lock:
            return [
                {"peer_id": pid, "name": p["name"], "token": p["token"]}
                for pid, p in self._peers.items()
            ]

    def is_valid_token(self, token: str) -> bool:
        """Constant-time check whether a token belongs to any paired peer."""
        import hmac
        with self._lock:
            return any(
                hmac.compare_digest(p["token"], token)
                for p in self._peers.values()
            )
