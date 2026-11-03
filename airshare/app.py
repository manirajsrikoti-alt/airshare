"""Unified AirShare entry point: receiver + discovery + sender in one process.

Run with: airshare [--no-camera] [--port PORT] [--device-name NAME]
"""
import argparse
import logging
import socket
import threading

from airshare import config
from airshare.receiver import server as receiver_server
from airshare.receiver.discovery import DiscoveryBroadcaster
from airshare.shared.protocol import ReceiverStatus

logger = logging.getLogger(__name__)


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class AirShareApp:
    """Runs the receiver (Flask + UDP discovery) and, when a camera is
    available, the sender loop. Camera failure degrades to receiver-only
    mode instead of crashing."""

    def __init__(self, port: int = None, device_name: str = None, no_camera: bool = False):
        self.port = port or config.RECEIVER_PORT
        self.device_name = device_name or socket.gethostname() or "AirShare"
        self.no_camera = no_camera
        self.receiver_only = no_camera
        self.sender = None
        self._sender_thread = None
        self._broadcaster = None

    # ---- sender side ----

    def start_sender(self) -> bool:
        """Start the sender in a background thread. Returns False (and switches
        to receiver-only mode) when the camera is unavailable or --no-camera
        was given."""
        if self.no_camera:
            self.receiver_only = True
            logger.info("--no-camera given: running in receiver-only mode")
            return False

        # Deferred import so --no-camera / headless use never requires cv2+mediapipe
        from airshare.sender.main import AirShareSender

        try:
            sender = AirShareSender()
        except Exception as e:
            self.receiver_only = True
            logger.warning(f"Sender unavailable ({e}) — running in receiver-only mode")
            return False

        if not sender.initialize():
            self.receiver_only = True
            logger.warning(
                "Camera unavailable — running in receiver-only mode. "
                "The dashboard still receives screenshots from other devices."
            )
            return False

        self.sender = sender
        self.receiver_only = False

        # Keep the dashboard gesture switch in sync with the sender's G hotkey
        orig_set = sender.set_gestures_enabled
        def _synced_set(enabled):
            orig_set(enabled)
            receiver_server._gestures_enabled = bool(enabled)
        sender.set_gestures_enabled = _synced_set

        self._sender_thread = threading.Thread(target=sender.run, daemon=True)
        self._sender_thread.start()
        logger.info("Sender started (gesture tracking OFF — press G or use the dashboard to enable)")
        return True

    # ---- hooks for the receiver server ----

    def peer_list(self) -> list:
        """Discovered receiver peers for GET /api/peers."""
        if not self.sender:
            return []
        return [
            {
                "peer_id": f"{r.host}:{r.port}",
                "name": r.device_name,
                "host": r.host,
                "port": r.port,
            }
            for r in self.sender.network.get_discovered_receivers()
        ]

    def apply_target(self, peer_id: str):
        """Resolve a peer_id (host:port) to a discovered receiver and set it
        as the sender's default upload target."""
        if not self.sender:
            return
        for r in self.sender.network.get_discovered_receivers():
            if f"{r.host}:{r.port}" == peer_id:
                self.sender.network.set_target(r)
                return
        host, _, port = peer_id.rpartition(":")
        if host and port.isdigit():
            self.sender.network.set_target(ReceiverStatus(
                device_name=f"Receiver at {host}", host=host, port=int(port),
            ))

    # ---- lifecycle ----

    def run(self):
        """Start everything; Flask serves in the main thread."""
        receiver_server._device_name = self.device_name
        receiver_server.configure_runtime(
            peer_provider=self.peer_list,
            target_hook=self.apply_target,
            gesture_hook=self._gesture_hook,
        )

        self.start_sender()
        receiver_server.set_mode("receiver-only" if self.receiver_only else "full")
        if self.receiver_only:
            logger.warning(
                "RECEIVER-ONLY MODE: no camera/sender. Dashboard at "
                f"http://{_get_local_ip()}:{self.port}"
            )

        self._broadcaster = DiscoveryBroadcaster(
            device_name=self.device_name,
            port=self.port,
            host=_get_local_ip(),
        )
        self._broadcaster.start()

        logger.info(f"AirShare '{self.device_name}' dashboard: http://{_get_local_ip()}:{self.port}")
        try:
            receiver_server.app.run(
                host=config.RECEIVER_HOST, port=self.port, debug=False, threaded=True,
            )
        finally:
            self.stop()

    def stop(self):
        if self.sender:
            self.sender.stop()
        if self._broadcaster:
            self._broadcaster.stop()

    def _gesture_hook(self, enabled: bool):
        if self.sender:
            self.sender.set_gestures_enabled(enabled)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airshare",
        description="Huawei-style touchless gesture screenshot & laptop transfer",
    )
    parser.add_argument("--no-camera", action="store_true",
                        help="run in receiver-only mode (no webcam/sender)")
    parser.add_argument("--port", type=int, default=config.RECEIVER_PORT,
                        help=f"dashboard/receiver port (default: {config.RECEIVER_PORT})")
    parser.add_argument("--device-name", default=None,
                        help="name advertised to other AirShare devices")
    return parser


def main(argv=None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    app = AirShareApp(
        port=args.port,
        device_name=args.device_name,
        no_camera=args.no_camera,
    )
    app.run()


if __name__ == "__main__":
    main()
