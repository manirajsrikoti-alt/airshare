"""Network client for uploading screenshots to receiver."""
import logging
import time
import threading
import socket
from typing import Optional, Callable

import requests

from airshare import config
from airshare.shared.protocol import ReceiverStatus, TransferResponse
from airshare.receiver.discovery import DiscoveryListener

logger = logging.getLogger(__name__)


class NetworkClient:
    """Handles discovery, connection, and file transfer to the receiver."""

    def __init__(self):
        self._listener = DiscoveryListener()
        self._connected_receiver: Optional[ReceiverStatus] = None
        self._discovered: dict[str, ReceiverStatus] = {}
        self._upload_callback: Optional[Callable] = None
        self._on_discovery_callback: Optional[Callable] = None

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
                logger.info(f"Connected to receiver: {receiver.device_name}")
                return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
        return False

    def connect_manual(self, host: str, port: int = 5000) -> bool:
        """Manually connect to a receiver by IP."""
        receiver = ReceiverStatus(
            device_name=f"Receiver at {host}",
            host=host,
            port=port,
        )
        return self.connect_to_receiver(receiver)

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

    def upload_screenshot(self, file_data: bytes, filename: str,
                          sender_name: str = "Laptop A",
                          callback: Optional[Callable] = None) -> TransferResponse:
        """Upload a screenshot to the connected receiver. Can run in background."""
        if not self._connected_receiver:
            return TransferResponse(success=False, error="No receiver connected")

        url = f"{self._connected_receiver.url}/api/upload"

        try:
            files = {"image": (filename, file_data, "image/png")}
            data = {
                "sender_name": sender_name,
                "timestamp": str(time.time()),
            }

            resp = requests.post(
                url,
                files=files,
                data=data,
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
            error = "Connection refused - receiver unavailable"
            logger.error(error)
            return TransferResponse(success=False, error=error)
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
