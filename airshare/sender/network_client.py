"""Network client for uploading screenshots to receiver."""
import logging
import time
import threading
import socket
from typing import Optional, Callable

import requests

from airshare import config
from airshare.shared.pairing import PairingStore
from airshare.shared.protocol import ReceiverStatus, TransferResponse
from airshare.receiver.discovery import DiscoveryListener

logger = logging.getLogger(__name__)


class NetworkClient:
    """Handles discovery, connection, and file transfer to the receiver."""

    def __init__(self):
        self._listener = DiscoveryListener()
        self._connected_receiver: Optional[ReceiverStatus] = None
        self._discovered: dict[str, ReceiverStatus] = {}
        self._device_id = socket.gethostname()
        self._pairing = PairingStore()
        self._token: Optional[str] = self._pairing.get_token(self._device_id)
        self._upload_callback: Optional[Callable] = None
        self._on_discovery_callback: Optional[Callable] = None
        self._target: Optional[ReceiverStatus] = None
        self._on_reconnect_callback: Optional[Callable] = None
        self._reconnect_running = False
        self._reconnect_thread: Optional[threading.Thread] = None

        self._listener.set_callback(self._on_receiver_discovered)

    def start_discovery(self, callback: Optional[Callable] = None):
        """Start listening for receiver broadcasts."""
        self._on_discovery_callback = callback
        self._listener.start()
        logger.info("Discovery listener started")

    def stop_discovery(self):
        """Stop discovery."""
        self._listener.stop()

    def _on_receiver_discovered(self, status: ReceiverStatus):
        """Called when a new receiver is found."""
        key = f"{status.host}:{status.port}"
        self._discovered[key] = status
        logger.info(f"Receiver found: {status.device_name} at {status.host}:{status.port}")
        if self._on_discovery_callback:
            self._on_discovery_callback(status)

    def get_discovered_receivers(self) -> list[ReceiverStatus]:
        """List of discovered receivers."""
        return list(self._discovered.values())

    def connect_to_receiver(self, receiver: ReceiverStatus) -> bool:
        """Connect to a specific receiver."""
        try:
            resp = requests.get(f"{receiver.url}/api/status", timeout=config.HTTP_TIMEOUT)
            if resp.status_code == 200:
                self._connected_receiver = receiver
                self._target = receiver
                logger.info(f"Connected to receiver: {receiver.device_name}")
                return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
        return False

    def connect_manual(self, host: str, port: int = config.RECEIVER_PORT) -> bool:
        """Manually connect to a receiver by IP."""
        receiver = ReceiverStatus(
            device_name=f"Receiver at {host}",
            host=host,
            port=port,
        )
        return self.connect_to_receiver(receiver)

    def set_target(self, peer: ReceiverStatus):
        """Set the default upload target without a connectivity check."""
        self._connected_receiver = peer
        self._target = peer
        logger.info(f"Upload target set: {peer.device_name} at {peer.host}:{peer.port}")

    def disconnect(self):
        """Disconnect from receiver."""
        self._connected_receiver = None

    @property
    def is_connected(self) -> bool:
        return self._connected_receiver is not None

    @property
    def receiver_name(self) -> str:
        if self._connected_receiver:
            return self._connected_receiver.device_name
        return "None"

    @property
    def receiver(self) -> Optional[ReceiverStatus]:
        return self._connected_receiver

    def set_reconnect_callback(self, callback: Optional[Callable]):
        """Set a callback fired with the ReceiverStatus when a reconnect succeeds."""
        self._on_reconnect_callback = callback

    def _find_fresh_receiver(self, target: ReceiverStatus) -> Optional[ReceiverStatus]:
        """Find a non-stale discovered receiver matching the target's host/port."""
        for r in self._listener.receivers:
            if r.host == target.host and r.port == target.port:
                return r
        for r in self._discovered.values():
            if r.host == target.host and r.port == target.port:
                return r
        return None

    def attempt_reconnect(self) -> bool:
        """Try once to reconnect to the last target. Returns True on success."""
        if self._connected_receiver is not None or self._target is None:
            return self._connected_receiver is not None
        match = self._find_fresh_receiver(self._target)
        if not match:
            return False
        self._connected_receiver = match
        logger.info(f"Reconnected to receiver: {match.device_name} at {match.host}:{match.port}")
        if self._on_reconnect_callback:
            self._on_reconnect_callback(match)
        return True

    def start_reconnect(self, callback: Optional[Callable] = None):
        """Start the background reconnect loop."""
        if callback is not None:
            self.set_reconnect_callback(callback)
        if self._reconnect_running:
            return
        self._reconnect_running = True
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()
        logger.info("Reconnect loop started")

    def stop_reconnect(self):
        """Stop the background reconnect loop."""
        self._reconnect_running = False
        if self._reconnect_thread:
            self._reconnect_thread.join(timeout=3)
            self._reconnect_thread = None
        logger.info("Reconnect loop stopped")

    def _reconnect_loop(self):
        while self._reconnect_running:
            try:
                if self._connected_receiver is None and self._target is not None:
                    self.attempt_reconnect()
            except Exception as e:
                logger.debug(f"Reconnect check error: {e}")
            time.sleep(config.RECONNECT_INTERVAL)

    def pair(self, pin: str) -> bool:
        """Pair with the connected receiver using its 6-digit PIN.

        On success the issued token is stored locally and sent automatically
        on subsequent uploads. Returns True if pairing succeeded.
        """
        if not self._connected_receiver:
            logger.error("Cannot pair: no receiver connected")
            return False

        url = f"{self._connected_receiver.url}/api/pair"
        try:
            resp = requests.post(
                url,
                json={
                    "pin": pin,
                    "device_id": self._device_id,
                    "device_name": socket.gethostname(),
                },
                timeout=config.HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                self._token = resp.json()["token"]
                self._pairing.add_peer(
                    self._device_id, socket.gethostname(), self._token,
                )
                logger.info("Pairing successful")
                return True
            logger.error(f"Pairing failed with status {resp.status_code}")
        except Exception as e:
            logger.error(f"Pairing error: {e}")
        return False

    def upload_screenshot(self, file_data: bytes, filename: str,
                          sender_name: str = "Laptop A",
                          callback: Optional[Callable] = None) -> TransferResponse:
        """Upload a screenshot to the connected receiver. Can run in background."""
        if not self._connected_receiver:
            return TransferResponse(success=False, error="No receiver connected")

        attempts = 1 + config.UPLOAD_RETRIES
        for attempt in range(attempts):
            try:
                return self._post_upload(file_data, filename, sender_name, callback)
            except requests.exceptions.ConnectionError:
                logger.error(
                    f"Connection refused - receiver unavailable "
                    f"(attempt {attempt + 1}/{attempts})"
                )
                if attempt + 1 < attempts:
                    self._rediscover_target()
        error = "Connection refused - receiver unavailable"
        response = TransferResponse(success=False, error=error)
        if callback:
            callback(False, response)
        return response

    def _rediscover_target(self):
        """Refresh the connection from discovery before a retry."""
        if self._target is None:
            return
        match = self._find_fresh_receiver(self._target)
        if match:
            self._connected_receiver = match
            logger.info(f"Re-discovered receiver at {match.host}:{match.port}")

    def _post_upload(self, file_data: bytes, filename: str,
                     sender_name: str,
                     callback: Optional[Callable]) -> TransferResponse:
        """Single upload attempt against the connected receiver."""
        url = f"{self._connected_receiver.url}/api/upload"

        try:
            files = {"image": (filename, file_data, "image/png")}
            data = {
                "sender_name": sender_name,
                "timestamp": str(time.time()),
            }

            headers = {}
            if self._token:
                headers["X-AirShare-Token"] = self._token

            resp = requests.post(
                url,
                files=files,
                data=data,
                headers=headers,
                timeout=config.TRANSFER_TIMEOUT,
            )

            if resp.status_code == 200:
                result = resp.json()
                response = TransferResponse.from_dict(result)
                logger.info(f"Upload successful: {response.filename}")
                if callback:
                    callback(True, response)
                return response
            else:
                error_msg = f"Upload failed with status {resp.status_code}"
                logger.error(error_msg)
                response = TransferResponse(success=False, error=error_msg)
                if callback:
                    callback(False, response)
                return response

        except requests.exceptions.ConnectionError:
            raise  # handled by the retry loop in upload_screenshot
        except requests.exceptions.Timeout:
            error = "Transfer timed out"
            logger.error(error)
            return TransferResponse(success=False, error=error)
        except Exception as e:
            error = f"Transfer error: {e}"
            logger.error(error)
            return TransferResponse(success=False, error=error)

    def upload_screenshot_async(self, file_data: bytes, filename: str,
                                sender_name: str = "Laptop A",
                                callback: Optional[Callable] = None):
        """Upload in a background thread."""
        thread = threading.Thread(
            target=self.upload_screenshot,
            args=(file_data, filename, sender_name, callback),
            daemon=True,
        )
        thread.start()
        return thread
