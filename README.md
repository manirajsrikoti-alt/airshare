# AirShare

Huawei-style touchless gesture screenshot & laptop transfer. Grab a screenshot
out of the air with a fist, then flick it across the room to a nearby laptop —
no cables, no chat apps, no cloud. Both machines run one command on the same
LAN; either side can send to the other.

The magic is the *feel*: a fist indicator on grab, a thumbnail that shrinks and
flies off-screen toward the peer, and an arrival ripple on the receiver's
dashboard (see `docs/animation-spec.md`).

## Install

From source (current):

```bash
git clone https://github.com/manirajsrikoti-alt/airshare.git
cd airshare
pip install -e .
```

From PyPI (coming soon):

```bash
pip install airshare-lan
```

> The PyPI distribution is named `airshare-lan`; the import package and the
> console command are both just `airshare`.

Requires Python 3.10+, a webcam on the sending side, and both machines on the
same LAN. Runs on macOS and Linux (tested in CI on Ubuntu and macOS, Python
3.10 and 3.12).

## Quick start

Run the same command on **both** laptops:

```bash
airshare
```

Each machine starts a receiver (Flask dashboard + upload server), advertises
itself via UDP discovery, and — if a camera is available — starts the gesture
sender. Open the dashboard printed in the logs
(`http://<local-ip>:5077` by default).

### Pair once (PIN)

1. On the machine you want to send *to*, find its 6-digit pairing PIN — it is
   printed in that machine's terminal at startup and shown on its dashboard
   **only when opened from that same machine** (it is never served to other
   LAN clients).
2. On the sending machine's dashboard, find the peer under *Discovered
   Peers*, enter the PIN in its row, and click **Pair**.
3. The receiver issues a per-peer token; from then on transfers between those
   two machines need no further interaction.

### Gestures

| Gesture | Action |
|---|---|
| ✊ fist grab (open hand → close, hold ~8 frames) | Capture a screenshot |
| → flick (fast horizontal palm swipe) | Send the grabbed screenshot to the paired peer |
| ✋ open palm (held still ~20 frames) | Cancel the pending screenshot |

Press `G` (or use the dashboard switch) to toggle gesture tracking. Animation
timings, easing, and overlay layout are specified in
[`docs/animation-spec.md`](docs/animation-spec.md).

Headless machine? Run `airshare --no-camera` for a receiver-only node.

## Security model

AirShare is a **LAN tool for trusted home/office networks**, designed against
casual snooping — not against a determined attacker on your network.

- **PIN pairing:** a 6-digit PIN is required before the first transfer
  between two machines. There is no open upload endpoint. The PIN is printed
  to the receiver's terminal and shown on its dashboard only to browsers on
  the same machine (loopback) — never to LAN clients. PIN guesses are
  compared in constant time and rate-limited to 5 failures per minute per
  client.
- **Loopback-only dashboard controls:** the actions that change state —
  pairing with a peer, selecting the upload target, toggling gestures — only
  accept requests from the machine itself (127.0.0.1/::1); remote requests
  get 403.
- **Per-peer tokens:** pairing issues a random 128-bit token per peer, sent as
  the `X-AirShare-Token` header on every upload. Tokens are stored in
  `~/.airshare/peers.json` (mode 600), keyed by the peer's `host:port` so each
  receiver keeps its own token.
- **Known limitation:** dashboard read routes (peer list, gallery) are not
  token-authenticated — anyone on the LAN can view them. Traffic is plain
  HTTP; do not use on untrusted networks.

## Configuration

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `AIRSHARE_PORT` | `5077` | Receiver/dashboard port (avoids macOS AirPlay on 5000) |
| `AIRSHARE_DEBUG` | `0` | Set to `1` for debug mode |

CLI flags: `airshare --help` (`--no-camera`, `--port`, `--device-name`).

Key tunables in `airshare/config.py`:

| Setting | Default | Description |
|---|---|---|
| `RECEIVER_PORT` | 5077 | Upload/dashboard port |
| `DISCOVERY_PORT` | 5001 | UDP broadcast discovery port |
| `GRAB_HOLD_FRAMES` | 8 | Frames a fist must be held to trigger GRAB |
| `CANCEL_HOLD_FRAMES` | 20 | Frames a still open palm must be held to CANCEL |
| `FLICK_MIN_TOTAL_DISPLACEMENT` | 0.10 | Min horizontal travel (normalized) for a flick |
| `UPLOAD_RETRIES` | 1 | Extra upload attempts after a ConnectionError |
| `RECONNECT_INTERVAL` | 5 | Seconds between background reconnect checks |
| `PEER_STALE_TIMEOUT` | 30 | Drop discovered receivers not seen for this long |
| `MAX_UPLOAD_SIZE` | 50 MB | Upload size cap |

## Development

```bash
pip install -e .
python -m pytest        # 150 tests
```

CI runs the suite on Ubuntu and macOS with Python 3.10 and 3.12.

## License

MIT — see [LICENSE](LICENSE).
