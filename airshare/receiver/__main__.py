"""Allow running as: python -m airshare.receiver"""
import logging
from airshare.receiver.server import start_receiver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

if __name__ == "__main__":
    start_receiver()
