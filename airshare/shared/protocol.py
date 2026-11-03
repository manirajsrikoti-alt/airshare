"""Shared network protocol definitions for AirShare."""
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class TransferRequest:
    """Payload sent with each screenshot upload."""
    sender_name: str = "Laptop A"
    device_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    filename: str = ""


@dataclass
class TransferResponse:
    """Response from the receiver after upload."""
    success: bool = False
    filename: str = ""
    received_at: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "TransferResponse":
        return cls(
            success=data.get("success", False),
            filename=data.get("filename", ""),
            received_at=data.get("received_at", ""),
            error=data.get("error", ""),
        )


@dataclass
class ReceiverStatus:
    """Status broadcast by the receiver for discovery."""
    device_name: str = "Laptop B"
    port: int = 5000
    host: str = ""
    version: str = "1.0.0"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_broadcast(self) -> str:
        return f"AIRSHARE_RECEIVER|device_name={self.device_name}|port={self.port}|host={self.host}|version={self.version}"

    @classmethod
    def from_broadcast(cls, message: str) -> Optional["ReceiverStatus"]:
        if not message.startswith("AIRSHARE_RECEIVER"):
            return None
        parts = message.split("|")
        data = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                data[key] = value
        return cls(
            device_name=data.get("device_name", "Unknown"),
            port=int(data.get("port", 5000)),
            host=data.get("host", ""),
            version=data.get("version", "1.0.0"),
        )


@dataclass
class DeviceInfo:
    """A discovered receiver device."""
    name: str
    host: str
    port: int
    status: str = "Ready"
    last_seen: float = field(default_factory=time.time)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "status": self.status,
            "url": self.url,
        }
