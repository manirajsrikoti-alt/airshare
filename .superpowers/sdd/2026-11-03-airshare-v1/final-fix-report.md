# AirShare v1.0 — Final-Review Fix Wave Report

Date: 2026-11-03. Baseline: 120 tests passing. Final: **150 tests passing** (30 new in `airshare/tests/test_security_fixes.py`).

## Critical 1 — Pairing flow unreachable

- New local endpoint `POST /api/pair-peer {peer_id, pin}` in `airshare/receiver/server.py` (loopback-only; 503 when no sender hook, 400 on missing fields, 403 on pairing failure, 200 + `{success: true}` on success).
- New app hook `AirShareApp.pair_with_peer(peer_id, pin)` in `airshare/app.py`: resolves the `peer_id` against currently-discovered `ReceiverStatus` entries (unknown peer → False), calls `network.connect_to_receiver(...)` then `network.pair(pin)`; token is stored in the sender's `PairingStore` (see Critical/Important 5). Wired via `configure_runtime(..., pair_hook=...)`.
- Dashboard: each unpaired discovered peer row in `airshare/receiver/static/app.js` now has a PIN input + **Pair** button posting to `/api/pair-peer`; paired rows show a "✓ Paired" badge. `airshare/app.py::peer_list` now reports a `paired` flag from the sender-side store, and `api_peers` prefers it.
- Tests: `TestPairPeerEndpoint` (success/failure/missing-fields/no-hook), `TestPairWithPeer`.

## Critical 2 — PIN served to every LAN client

- `index()` renders `pin` only when `request.remote_addr` is loopback (`127.*`/`::1`); remote clients get the dashboard with an explanatory note instead of the PIN (`templates/index.html` `{% if pin %}` block).
- `server.print_pin()` prints the PIN to the receiver's terminal; called from `start_receiver()` and from `AirShareApp.run()` (headless startup).
- Tests: `TestPinPrivacy` (loopback shows, remote hides, terminal print).

## Critical 3 — Unauthenticated dashboard control endpoints

- `_loopback_only` decorator in `server.py` applied to `/api/target`, `/api/gestures`, `/api/pair-peer` → remote requests get 403.
- `AirShareApp.apply_target` now returns bool and only accepts **discovered** peers (uses the discovered `ReceiverStatus`) or **already-paired** peers (sender-side store, `host:port` key); arbitrary host:port construction removed. `api_target` returns 400 and does not persist when the hook rejects.
- Tests: `TestLoopbackGating`, `TestTargetValidation`, `TestApplyTargetPolicy`.

## Critical 4 — Wheel missing templates/static

- Added to `pyproject.toml`:
  ```toml
  [tool.setuptools.package-data]
  "airshare.receiver" = ["templates/*.html", "static/*.css", "static/*.js"]
  ```
- Verification: `python3 -m build` (build 1.5.0 present; would have been pip-installed if missing) produced `dist/airshare_lan-1.0.0-py3-none-any.whl`; `pip3 install --no-deps --target /tmp/wheeltest dist/*.whl`, then confirmed:
  - `/tmp/wheeltest/airshare/receiver/templates/index.html`
  - `/tmp/wheeltest/airshare/receiver/static/app.js`
  - `/tmp/wheeltest/airshare/receiver/static/style.css`
  all exist. Temp dirs (`/tmp/wheeltest`, `build/`, `dist/`) removed afterwards.

## Important 5 — Sender token keyed by own hostname

- `NetworkClient` (`airshare/sender/network_client.py`) now keys the sender-side `PairingStore` by the target receiver's `host:port` (`_peer_key`). `pair()` stores under that key; `_load_token_for(receiver)` refreshes the cached `_token` on `connect_to_receiver`, `set_target`, `attempt_reconnect`, and `_rediscover_target`; `disconnect()` clears it. Multiple receivers each keep their token.
- Tests: `TestSenderTokenKeying` (store key, per-receiver switching, upload header).

## Important 6 — /api/pair rate limit + constant-time compare

- Max 5 failed PIN attempts per 60 s per remote addr → 429 (`_pair_failures` dict, `PAIR_MAX_FAILURES`/`PAIR_FAILURE_WINDOW`); successful pairing clears the counter. PIN check uses `hmac.compare_digest`.
- Tests: `TestPairRateLimit` (429 after 5, per-addr isolation, success resets).

## Important 7 — Data dirs inside installed package

- `RECEIVER_UPLOAD_DIR` → `~/.airshare/received`, `SCREENSHOT_DIR` → `~/.airshare/screenshots` in `airshare/config.py`; import-time `os.makedirs` removed — `StorageManager.__init__` and `ScreenshotCapture` create dirs lazily.
- Tests: `TestDataDirs`.

## Important 8 — README

- Pairing instructions rewritten (PIN from the target machine's terminal/localhost dashboard; Pair button on sender's dashboard).
- Security model section updated: loopback-gated dashboard controls, PIN never served to LAN clients, rate limiting + constant-time compare, tokens keyed by `host:port`. Known-limitation note (plain HTTP, unauthenticated read routes) kept.
- Test count updated to 150.

## Minors

- Own-broadcast filter: `AirShareApp.peer_list` drops entries matching this machine's IP+port (incl. 127.0.0.1) — test `TestPeerListSelfFilter`.
- `/api/gestures` POST returns 400 on missing/non-bool `enabled` — `TestGesturesValidation`.
- Dropped dead config `THUMB_DWELL_MS`, `THUMB_CORNER_RADIUS_PCT` and dead `CalibrationData` `capture_*`/`transfer_*` fields — `TestDataDirs.test_dead_config_keys_removed`, `TestCalibrationData`.
- Upload 500 returns generic `"internal upload error"` instead of `str(e)` — `TestUploadErrorMessage`.
- `.gitignore` already covers egg-info via `*.egg-info/` — no change needed.

## Commands & results

- `python3 -m pytest` → **150 passed in ~1.6 s** (baseline was 120 passed).
- `python3 -m build` → built sdist + wheel successfully.
- `pip3 install --no-deps --target /tmp/wheeltest dist/airshare_lan-1.0.0-py3-none-any.whl` + `ls` → templates/static present (paths above).

## Out of scope (per instructions)

Live two-laptop run, PyPI publish, macOS cv2 threading validation — not attempted.
