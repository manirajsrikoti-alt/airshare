"""UDP broadcast discovery for the receiver."""
import socket
import threading
import time
import logging

from airshare import config
from airshare.shared.protocol import ReceiverStatus

logger = logging.getLogger(__name__)


class DiscoveryBroadcaster:
    """Periodically broadcasts receiver presence on the local network via UDP."""

    def __init__(self, device_name: str = "AirShare Receiver",
                 port: int = 5000, host: str = ""):
        self.status = ReceiverStatus(
            device_name=device_name,
            port=port,
            host=host,
        )
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        """Start broadcasting in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()
        logger.info(f"Discovery broadcaster started: {self.status.device_name}")

    def stop(self):
        """Stop broadcasting."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("Discovery broadcaster stopped")

    def _broadcast_loop(self):
        """Main broadcast loop."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1)

        message = self.status.to_broadcast().encode("utf-8")

        while self._running:
            try:
                sock.sendto(message, ("255.255.255.255", config.DISCOVERY_PORT))
                sock.sendto(message, ("127.0.0.1", config.DISCOVERY_PORT))
            except Exception as e:
                logger.debug(f"Broadcast send error: {e}")

            time.sleep(config.DISCOVERY_INTERVAL)

        sock.close()


class DiscoveryListener:
    """Listens for receiver broadcasts on the local network."""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._receivers: dict[str, ReceiverStatus] = {}
        self._callback = None

    def set_callback(self, callback):
        """Set a callback function(new_receiver_status) for when a new receiver is found."""
        self._callback = callback

    def start(self):
        """Start listening in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Discovery listener started")

    def stop(self):
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("Discovery listener stopped")

    @property
    def receivers(self) -> list[ReceiverStatus]:
        """List of discovered receivers."""
        # Filter out stale entries (> 10 seconds old)
        now = time.time()
        return [
            r for r in self._receivers.values()
            if now - r.host < 30  # We use host field temporarily for last_seen
        ]

    def _listen_loop(self):
        """Main listening loop."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass  # Windows doesn't support SO_REUSEPORT

        sock.bind(("", config.DISCOVERY_PORT))
        sock.settimeout(2)

        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
                message = data.decode("utf-8")
                status = ReceiverStatus.from_broadcast(message)
                if status and addr[0] != "127.0.0.1":
                    status.host = addr[0]
                    key = f"{addr[0]}:{status.port}"
                    if key not in self._receivers:
                        logger.info(f"Discovered receiver: {status.device_name} at {addr[0]}:{status.port}")
                        if self._callback:
                            self._callback(status)
                    self._receivers[key] = status
            except socket.timeout:
                continue
            except Exception as e:
                logger.debug(f"Listen error: {e}")

        sock.close()
