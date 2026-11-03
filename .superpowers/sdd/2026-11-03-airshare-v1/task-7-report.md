# Task 7 Report: Reliability — reconnect, retry, stale peers, hold tuning

## What I implemented

1. **Stale peer filtering bug fix** (`airshare/receiver/discovery.py`, `airshare/shared/protocol.py`)
   - `DiscoveryListener.receivers` compared `now - r.host < 30` where `host` is a string — a live crash/misbehavior.
   - Added a real `last_seen: float = field(default_factory=time.time)` field to `ReceiverStatus`.
   - `receivers` now filters on `now - r.last_seen < config.PEER_STALE_TIMEOUT` (new config, 30s).
   - Broadcast wire format unchanged (`last_seen` is not serialized; each received broadcast creates a fresh status so `last_seen` is always "now" on receipt).

2. **Upload retry** (`airshare/sender/network_client.py`)
   - `upload_screenshot` now runs up to `1 + config.UPLOAD_RETRIES` (config `UPLOAD_RETRIES = 1`) attempts.
   - The single-attempt POST moved to `_post_upload`; `ConnectionError` is re-raised there and caught by the retry loop.
   - Between attempts, `_rediscover_target()` refreshes `_connected_receiver` from freshly discovered peers (host/port match on last target).
   - After retries are exhausted, a failed `TransferResponse` is returned and the callback fires with `False`.

3. **Background reconnect loop** (`airshare/sender/network_client.py`)
   - `set_target`/`connect_to_receiver` now remember the target in `self._target`.
   - `attempt_reconnect()`: one-shot reconnect — when disconnected, looks for a non-stale discovered receiver matching the target's host/port, restores the connection, and fires the reconnect callback. Ignores stale entries.
   - `start_reconnect(callback)` / `stop_reconnect()`: daemon thread looping every `config.RECONNECT_INTERVAL` (new config, 5s), calling `attempt_reconnect` while disconnected.

4. **Config** (`airshare/config.py`)
   - `GRAB_HOLD_FRAMES` and `CANCEL_HOLD_FRAMES` already existed from Task 5 — verified, no change needed.
   - Added `UPLOAD_RETRIES = 1`, `RECONNECT_INTERVAL = 5`, `PEER_STALE_TIMEOUT = 30`.

## TDD evidence

- **RED:** wrote `airshare/tests/test_reliability.py` (10 tests) first; ran — **10 failed** (`AttributeError` for `PEER_STALE_TIMEOUT`, missing reconnect API, no retry behavior, string-host TypeError covered by crash test).
- **GREEN:** implemented the changes; focused run — **10 passed in 0.18s**.
- **Full suite:** `python3 -m pytest -q` — **116 passed in 1.22s** (was 106 before; +10 new).

## Tests added (`airshare/tests/test_reliability.py`)

- Stale receiver filtered out; fresh kept; no crash on string `host`; `last_seen` refresh.
- Upload retried exactly once after `ConnectionError` then succeeds; failure reported after retries exhausted; callback reports final failure.
- `attempt_reconnect` fires callback when receiver reappears; returns False when absent; ignores stale entries; background loop fires when receiver reappears (with `RECONNECT_INTERVAL` monkeypatched to 0.05).

## Files changed

- `airshare/config.py` — new `UPLOAD_RETRIES`, `RECONNECT_INTERVAL`, `PEER_STALE_TIMEOUT`.
- `airshare/shared/protocol.py` — `ReceiverStatus.last_seen` field.
- `airshare/receiver/discovery.py` — stale filter on `last_seen`.
- `airshare/sender/network_client.py` — retry loop, `_post_upload`, `_rediscover_target`, reconnect loop API.
- `airshare/tests/test_reliability.py` — new, 10 tests.

## Self-review findings

- Retry only applies to `ConnectionError` (per brief); timeouts still fail immediately — intentional.
- `_rediscover_target` is a no-op when no target is known; retry then simply re-hits the same URL — safe fallback.
- Reconnect loop is opt-in (`start_reconnect`); existing callers are unaffected.
- `ReceiverStatus` gained a field; `from_broadcast` does not set it from the wire, so it defaults to receipt time — correct semantics.

## Concerns

- `attempt_reconnect` restores the connection without an HTTP `/api/status` health check (uses discovery freshness only); a freshly seen but hung receiver would be "reconnected" optimistically. Acceptable for v1.0 LAN scope.
- Reconnect thread is never started automatically; the sender app should call `start_reconnect()` after connecting — wiring into the app layer is outside this task's file scope.

---

# Follow-up: review findings (thread-safety, target cleanup, app wiring)

## Changes

1. **Thread-safety (Important):** added `self._lock = threading.Lock()` to `NetworkClient`. All reads/writes of `_connected_receiver` and `_target` now happen under the lock (`connect_to_receiver`, `set_target`, `disconnect`, `is_connected`, `receiver_name`, `receiver`, `attempt_reconnect`, `_reconnect_loop`, `_rediscover_target`, `_post_upload`, `pair`). The `_discovered` dict is also guarded (write in `_on_receiver_discovered`, snapshot-copy for iteration in `_find_fresh_receiver` and `get_discovered_receivers`), so listener-thread writes can no longer race reconnect-thread iteration. Callbacks always fire outside the lock. `start_reconnect` docstring now documents that the callback fires on the reconnect thread and app code must marshal to its own thread for UI.
2. **`disconnect()` clears `_target`** so an intentional disconnect stops the reconnect loop from reviving the connection.
3. **App wiring:** `AirShareSender.initialize()` (`airshare/sender/main.py`) now calls `self.network.start_reconnect()` right after `start_discovery`; `_cleanup()` calls `self.network.stop_reconnect()` before `stop_discovery()`.

## Tests

Added (TDD — all 4 failed RED before implementation):
- `test_disconnect_clears_target_and_stops_reconnect`, `test_disconnect_stops_reconnect_loop` (test_reliability.py)
- `TestSenderReconnectWiring::test_initialize_starts_reconnect`, `test_cleanup_stops_reconnect` (mock-level, test_app.py)

Older reconnect tests that simulated a drop via `disconnect()` were updated to clear `_connected_receiver` directly, since `disconnect()` is now intentional-disconnect semantics.

## Command & output

```
$ python3 -m pytest airshare/tests/test_reliability.py airshare/tests/test_app.py -v
28 passed in 0.84s
$ python3 -m pytest -q
120 passed in 3.13s
```

## Self-review / concerns

- Lock is never held across network I/O or callbacks — no deadlock risk identified.
- Reconnect restore is still discovery-freshness based (no HTTP health check) — unchanged from before, acceptable for v1.0.
