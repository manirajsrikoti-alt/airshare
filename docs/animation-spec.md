# AirShare Animation Spec

Reverse-engineered from public Huawei air-gesture demo videos (see "Sources").
Frame-count analysis on 60 fps and 25 fps clips; all times in milliseconds.
Values marked **(measured)** come from frame counts; **(approx)** are hand-tuned
from written descriptions / partial footage and must be treated as starting
points for the OpenCV overlay task.

## Constants

| Constant | Value | Basis |
|---|---|---|
| `GRAB_FREEZE_MS` | 400 | (measured, range 300–600) fist fully closes → frozen screenshot frame with white border appears. This is gesture-recognition latency, not animation. |
| `FLASH_MS` | 120 | (approx) full-screen white flash. Not clearly visible in the analysed 60 fps capture (EMUI 11 shows the bordered freeze-frame instead); classic EMUI screenshot flash lasts ~2 screen frames. Keep short: 100–150. |
| `SHRINK_MS` | 200 | (measured) full-screen frozen frame shrinks to the resting thumbnail in ~12 frames @ 60 fps. Motion is fast-then-slow (ease-out). |
| `FLY_MS` | 450 | (approx) thumbnail accelerates and flies off the screen edge toward the receiver. Based on HarmonyOS "air transfer" demos; the analysed EMUI clip has no fly-off (thumbnail slides out bottom-left instead). |
| `FLY_EASING` | ease-in (cubic) | (approx) flight starts slow and accelerates off-edge; contrast with the ease-out shrink. Implement as cubic-bezier(0.55, 0, 1, 0.45) equivalent in the OpenCV interpolator. |
| `RIPPLE_MS` | 600 | (approx) receiver-side expanding ripple/halo at the arrival point before the thumbnail lands. |
| `THUMB_SCALE_START` | 1.00 | (measured) shrink begins from the full-screen frozen frame. |
| `THUMB_SCALE_END` | 0.16 | (measured) resting thumbnail ≈ 15–18 % of screen width, bottom-left, with a ~4 px white border and rounded corners. |
| `THUMB_DWELL_MS` | 2500 | (measured) thumbnail idles at bottom-left for ~2.5–3 s before dismissing. In AirShare the `FLY_MS` flight replaces this dwell/dismiss (start flight after a short hold of ~400 ms). |
| `TOAST_MS` | 2000 | (approx) receiver-side arrival toast ("Screenshot received") visible duration. |
| `HOLD_MS` | 400 | (approx) pause with the thumbnail parked at its dwell position between the shrink and the fly-off. AirShare-specific: shorter than Huawei's 2.5–3 s dwell since we share immediately. |
| `TRAVEL_PATH` | bottom-left (dwell position) → right edge, slight upward arc | (approx) flight starts where the thumbnail rests after the shrink. Huawei's air-transfer demos show the payload moving toward the adjacent receiving device. Straight line with ~10 % vertical arc reads best at 60 fps overlay. |

## Storyboard (sender side)

| # | Phase | t (ms) | Visual |
|---|---|---|---|
| 0 | Idle / gesture armed | — | Live camera feed, subtle "hand detected" indicator. |
| 1 | Fist close detected | 0 | Grab gesture recognized; begin freeze countdown. |
| 2 | Screen freeze | 0 → `GRAB_FREEZE_MS` (400) | Live frame replaced by frozen frame; thin white border appears around the full screen. |
| 3 | White flash | freeze → +`FLASH_MS` (120) | Full-screen white overlay spikes to ~90 % opacity and fades. Overlaps start of shrink. |
| 4 | Shrink to thumbnail | freeze → +`SHRINK_MS` (200) | Frozen frame scales 1.00 → 0.16, ease-out, settling at bottom-left with white border + rounded corners. |
| 5 | Hold | +`HOLD_MS` (400) | Thumbnail idles briefly at the bottom-left dwell position (AirShare: shorter than Huawei's 2.5–3 s dwell, since we share immediately). |
| 6 | Fly off edge | +`FLY_MS` (450) | Thumbnail lifts off from the bottom-left dwell position and travels to the right edge on a slight upward arc, ease-in (accelerating), fading out in the last ~100 ms. |

## Storyboard (receiver side)

| # | Phase | t (ms) | Visual |
|---|---|---|---|
| 0 | Armed | — | Listening for sender. |
| 1 | Arrival ripple | 0 → `RIPPLE_MS` (600) | Expanding halo ring at the left-edge arrival point (mirror of sender's right-edge exit). |
| 2 | Thumbnail lands | overlaps ripple end | Thumbnail flies in from left edge, decelerating (ease-out), grows to `THUMB_SCALE_END` resting size. |
| 3 | Toast | 0 → `TOAST_MS` (2000) | "Screenshot received" toast, bottom-center, fade in 150 ms / hold / fade out 300 ms. |

## Measured reference: EMUI 11 Grabshot (Mate 40 Pro clip, 60 fps)

- t = 79.70 s: white-bordered full-screen freeze frame appears (fist closed ~0.3–0.6 s earlier).
- t = 79.70 → 79.90 s: freeze frame shrinks to bottom-left thumbnail (12 frames ≈ 200 ms), ease-out.
- Thumbnail rests at ≈ 16 % of screen width, bottom-left, white border, and persists ~2.5–3 s before sliding out left.
- No separate full-screen white flash is visible in this build; flash value above is therefore approximate.

## Sources

1. `https://youtu.be/jp7pmJytD60` — "How to Use Air Gesture on Huawei Mate 40 Pro, P40 Pro, Mate 30 Pro (Air Press, Air Scroll, Grabshot)" — 60 fps, primary measurement source (Grabshot segment t ≈ 78–105 s).
2. `https://youtu.be/CkT0ooVcryk` — "HUAWEI Mate30 Pro: AI Gesture Control (How-to video)" — 25 fps, official but heavily edited/stylized; used only for phase ordering, not timings.
3. `https://youtu.be/t7R8rCYnrOY` — HarmonyOS gesture photo-transfer clip (30 fps) — device screens too small to measure; used to confirm grab-on-A / release-on-B flow only.
4. `https://youtu.be/io7PfEzuijo` — "HUAWEI Nova 14 Pro – How to Enable and Use Air Gestures" — consulted; no measurable capture sequence.

Downloaded clips were kept in `/tmp` only and are not part of this repository.

## Notes for the implementation task

- Easing: shrink = ease-out (fast start); flight = ease-in (accelerating); landing on receiver = ease-out. Do not reuse one curve for all three.
- The white border around the frozen frame and thumbnail is a signature Huawei detail — keep it (≈ 4 px at 1080p, rounded corners ~2 % of width).
- `GRAB_FREEZE_MS` is recognition latency, not animation time; in AirShare it can be shortened to ~200 ms since our detector is local, but keep ≥ 150 ms so the freeze reads as intentional.
