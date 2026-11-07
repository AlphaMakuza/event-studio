# V2 acceptance record

Checked 2026-11-07, Windows, Python 3.12.10, development version
`2.0.0.dev1`, following live-camera implementation `fe2cabf`.

**Software checks pass within the scope below. Physical-camera acceptance is
still outstanding.** Motion estimates remain experimental. This is not a
claim of validated metrology or compatibility with every event camera.

| Check | Result and evidence |
| --- | --- |
| Existing environment | 76 tests passed, including live discovery/switching/error simulation, numerical fixtures, cancellation, session rollback and exports. `pip check` passed. NumPy 2.4.0, PySide6 6.10.1, Matplotlib 3.10.8. |
| Fresh installation | Created an isolated environment and installed both requirements files. All 76 tests passed; `pip check` passed. Resolved NumPy 2.5.4, PySide6 6.12.0, Matplotlib 3.11.2, imageio-ffmpeg 0.8.1. No application dependencies were taken from the existing environment. |
| Real MP4 | FFmpeg 9.0.2/libx264 encoded and decoded seven frames at 30000/1001 fps. Decoded frame timestamps matched the expected cadence; odd 65 by 49 output padded to 66 by 50. Export paths contained spaces. |
| Export recovery | Injected metadata commit failure followed by restoration failure. Previous CSV and metadata remained in a recovery directory with a journal naming the affected targets. Normal rollback and cancellation remain covered by the suite. |
| Sustained simulated live capture | 120 seconds using the actual capture worker, preview thread, renderers and recording path, with an offscreen Qt window: 15,986,688 received events; all six modes rendered; retained buffer never exceeded 100,000 events; no operation errors; workers closed cleanly. |
| Capture integrity | The 120-second run recorded 1,423,360 events during its initial recording period. Reloaded timestamps matched every generated timestamp exactly and both polarities were preserved. Preview continued after recording stopped. Hardware loss remained explicitly unknown. |
| Resource behavior | In that run, private-memory median grew 6.197 MiB between the initial and final steady sample groups; maximum GUI heartbeat gap 32 ms. This is a short sustained check, not an overnight leak certification. Preview queue observations were bounded; separate tests exercise request coalescing. |
| Native Windows UI | Additional 30-second run using the Windows Qt platform: 5,388,288 simulated events; all six views rendered; exact recorded timestamps; clean shutdown; maximum heartbeat gap 16 ms; steady memory median grew 0.824 MiB. |
| Large recording | Loaded all 12,210,297 events from `paper_200211_145805_0_0_td.csv` in 31.829 seconds, with a normal Qt event loop and maximum loading heartbeat gap 63 ms. A JSON session round trip preserved the current interval and all four event arrays exactly. |
| Large-recording rendering | A single 50 ms interval rendered in RAW 15 ms, heatmap 31 ms, persistence 16 ms, glow 63 ms, trail 31 ms, motion arrows 531 ms. These are individual measurements, not throughput guarantees. |

The native and offscreen sources were simulated. Their throughput and memory
results do not establish physical sensor, USB, driver or SDK performance.
Raw per-run JSON evidence remains locally under `artifacts/v2-acceptance/`.
User recordings and saved projects were not modified.

Changes made during acceptance:

- Added an optional bundled FFmpeg backend with a separate dependency file,
  encoder startup timeout and explicit frame-rate duration metadata.
- Corrected visual-manifest RAW/DERIVED/STYLIZED classification. Visual output
  remains a presentation artifact rather than an event recording.
- Preserved recovery copies when both export commit and rollback fail.
- Added repeatable sustained-capture and large-recording acceptance commands.

Reproduce from the repository root:

```powershell
python -m pip install -r requirements.txt -r requirements-video.txt
python -B -m unittest discover -s tests -v
python -m scripts.acceptance_soak --seconds 120 --output artifacts/v2-acceptance/soak.json
python -m scripts.acceptance_soak --seconds 30 --native --output artifacts/v2-acceptance/native-soak.json
python -m scripts.acceptance_recording data/converted/paper_200211_145805_0_0_td.csv --output artifacts/v2-acceptance/large-recording.json
```

The MP4 regression is skipped if neither a PATH encoder nor the optional
backend is installed. The large-recording command requires that local dataset;
it is not distributed with the source. Test timings depend on the machine.

Before declaring hardware acceptance complete, use the actual supported
camera/SDK/driver combination to verify detection, start/stop, each preview
mode, recording/reload, quiet scenes, unplug/reconnect, switching when multiple
devices are available, and longer sustained acquisition. Verify event counts
and hardware loss telemetry against what that SDK actually exposes. No physical
camera was exercised in this acceptance pass.

Before relying on motion measurements, validate direction and displacement
against known real motion in representative scenes. Synthetic translations pass,
but the earlier real recording accepted only one of 149 advanced-tracker links
at default settings. Display arrows can also be costly on dense scenes. The
current implementation has no claim of subpixel accuracy or universal real-time
motion tracking. See [V2 methods and limits](V2.md).
