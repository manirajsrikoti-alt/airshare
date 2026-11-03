# AirShare

Huawei-style touchless gesture screenshot & laptop transfer. Capture a
screenshot with an upward push gesture, then throw it to a nearby laptop
running the AirShare receiver.

## Install

```bash
pip install -e .
```

## Usage

```bash
airshare --help
```

Run the sender (camera + gestures) and receiver (Flask upload server)
separately until the unified app lands:

```bash
python -m airshare.sender.main
python -m airshare.receiver.main
```

## Configuration

Environment variables:

- `AIRSHARE_PORT` — receiver port (default `5077`, chosen to avoid macOS
  AirPlay Receiver on port 5000)
- `AIRSHARE_DEBUG` — set to `1` for debug mode

## Tests

```bash
python -m pytest
```

## License

MIT — see [LICENSE](LICENSE).
