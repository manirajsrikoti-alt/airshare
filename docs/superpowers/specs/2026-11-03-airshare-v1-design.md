# AirShare v1.0 — Design

Date: 2026-11-03
Status: implemented

## Intent

Turn the working AirShare prototype (`~/Documents/car/gesture-share/airshare`) into a polished,
open-source GitHub project: two laptops each install it, both run one `airshare` command, and
either side can grab a screenshot with a Huawei-style air gesture and flick it to the other
machine. The magic is the *feel*: fist-grab animation, thumbnail flying off-screen toward the
peer, arrival ripple on the receiver.

Why: the owner wants a daily-use tool, not a demo — reliability, security, and gesture feel
come before feature count.

## Goals

- One install path: `pip install airshare` (published to PyPI) from a public GitHub repo.
- Symmetric app: every install runs sender + receiver together; any laptop can send to any
  discovered, paired laptop on the LAN.
- Huawei-style gesture UX on a plain webcam:
  - fist-grab (hand open → close) captures a screenshot
  - overlay animation: fist indicator on grab, thumbnail shrink-and-fly toward the peer's
    direction, success ripple when the peer ACKs
  - receiver shows an arrival animation/toast in its dashboard (and native notification)
- Animation spec derived from analysis of Huawei demo videos via REA (reverse-engineer-anything
  skill) — timings, easing, sizes, sequence — documented in the repo and implemented in the overlay.
- Security: pairing PIN required before first transfer between two machines; transfers only
  between paired peers; no open upload endpoint.
- Reliability: gesture debounce/hold-time tuning to kill misfires, auto-reconnect on receiver
  drop, upload retry with backoff.
- Keep the existing 60-test suite green; add tests for pairing, protocol changes, and the
  gesture state machine additions.

## Non-goals

- Native installers / double-click apps / tray daemon (deferred; structure allows it later).
- Phone as receiver (web dashboard stays responsive, but no mobile app).
- File types beyond images, clipboard sync, multi-file transfer.
- Matching Huawei's detection range or power draw (they use a dedicated NPU + depth sensor;
  we use a webcam — the look and UX are matched, the hardware capability is not).

## Anti-goals

- Shipping with an unauthenticated upload endpoint (today's state — must be fixed).
- A gesture set so large it becomes unreliable: ship 2-3 gestures max (grab-screenshot,
  flick-send, open-palm cancel).
- Rewriting working modules that already pass tests.

## Constraints

- Python, cross-platform (macOS first; Linux/Windows kept working — config already abstracts).
- Existing stack preserved: Flask receiver, UDP broadcast discovery, mss capture,
  OpenCV/MediaPipe hand tracking, `requests` upload client.
- Default port must move off 5000 (conflicts with macOS AirPlay Receiver); pick a new default
  (e.g. 5077) with env override kept.
- No Huawei assets may be copied into the repo (copyright); REA extracts *specs* (timings,
  motion curves, layout), and all artwork is drawn original.

## Approach (chosen: A)

Considered:

- **A — Polish the existing Python app into a proper package.** Keep all working code and
  tests; add packaging (pyproject, entry point `airshare`), pairing, overlay animation,
  reliability fixes. Fastest path to something real; chosen by owner.
- B — Rebuild as a native-feeling desktop app (Tauri/Electron + sidecar). Best UX, ~3-4× work,
  discards working code. Deferred; option kept open by keeping the core UI-agnostic.
- C — Split repos (core lib + app). Premature; single repo with clean module boundaries instead.

## Decisions (made in conversation)

- Direction: daily-use tool — reliability + security + gesture feel over feature breadth.
- Both laptops run the identical install; sender and receiver are one app, both roles active.
- REA input is demo videos only (owner has no Huawei device or APK); animation is reconstructed
  from video analysis, not extracted assets.
- Pairing model: first connection shows a 6-digit PIN on the receiver; sender must enter it.
  Paired peers stored in a per-user config file; unpaired upload attempts are rejected.
- Repo: new public GitHub repo `airshare` under the `manirajsrikoti-alt` account, MIT license,
  code migrated from `Documents/car/gesture-share/airshare` with git init, README, CI running
  the test suite.
- Webcam gesture tracking is OFF by default and toggled by hotkey and dashboard switch —
  not always-on.
- Any laptop with the app installed can share to any other installed laptop on the LAN.
  Target selection: the dashboard lists discovered paired peers and one is selected as the
  default target; a flick sends to the selected peer (animation flies toward a fixed screen
  edge). Peer-to-direction mapping is a possible later enhancement, not v1.
- Pairing auth (builder call): the 6-digit PIN is exchanged once for a random per-peer token,
  stored on both machines, sent as a header on every upload. Plain HTTP on the LAN; threat
  model is casual snooping, not active MITM. The PIN itself is never reused as a credential.
- Huawei demo videos for the REA pass are sourced from the public web by the builder; fallback
  if unusable is a documented hand-tuned animation approximation.
- The existing push/throw gestures are REPLACED by the fist-grab set (grab, flick-send,
  palm-cancel); the corresponding gesture tests are rewritten. Gesture count stays at 3.

## Left to the builder

- Exact animation parameters — filled in by the REA video-analysis pass at plan time.
- New default port number; pairing storage format; notification mechanism per OS.
- Overlay rendering tech choice (current `overlay.py` uses OpenCV window vs. a transparent
  always-on-top window) — pick after checking what the current code does and what macOS allows.
- Gesture thresholds (confidence, hold frames) — tuned against real webcam use, values in config.

## Open questions for owner

None remaining.
