# Event-Based Studio

A scientific instrument with a studio layer on top. Explore event-camera
recordings, isolate precise intervals and spatial probes, measure events,
export original event tuples, and save reproducible sessions.

The V2 development build adds **Analysis → Advanced Analysis** (`Ctrl+Shift+A`)
for activity comparison, deterministic burst detection, annotations, frequency
analysis, estimated motion, explicit filters, batch analysis, and visual export.
See [V2 methods, usage, and verification limits](docs/V2.md).
**Live Camera** is also available directly on the project-browser screen.
It automatically lists compatible connected event cameras and previews the
selected camera, with the same RAW/Studio visualization choices. A native
Metavision SDK and matching device driver are required; missing camera support
is reported separately from a successful scan with no cameras detected.

The editor also includes a full-recording activity overview, linked time plots,
ROI comparison, recording diagnostics, and undo/redo. See
[exploration tools](docs/EXPLORATION.md) for controls, units, and limits.

The homepage offers **Image + text**, **Text only**, and **Large tiles** views,
with project/dataset search and sorting by name or last save. Your view choice
is remembered. Startup shows the transparent logo and retro loading label;
the homepage opens when the startup song finishes, with a fallback if audio
cannot play.

## Run

Windows download packaging is documented in [release preparation](docs/RELEASE.md).
The initial output is an unsigned internal preview ZIP with Python included;
The application is proprietary, copyright 2026 Alpha Makuza; see [LICENSE.txt](LICENSE.txt).
Public distribution is pending third-party compliance and clean-machine validation.
See [download instructions](docs/DOWNLOAD.md) for storage and optional integrations.

The title-bar **Glass / Original** selector compares the glass refresh with
the preserved previous appearance, including the original icons. It applies
to open windows immediately and remembers your choice. Glass uses Phosphor
icons through QtAwesome, square edges, translucent panels, and reflective
highlights. Windows 11 requests a native acrylic backdrop where supported;
other systems use painted glass. See [appearance notes](docs/APPEARANCE.md).

Windows PowerShell, from this directory:

```powershell
.\.venv\Scripts\python.exe -m event_studio.app
```

For a new environment, create a Python 3.12 virtual environment and install
`requirements.txt`. Development was verified with Python 3.12.10, NumPy 2.4.0,
PySide6 6.10.1, and Matplotlib 3.10.8.

For optional MP4 export, also install `requirements-video.txt`, or provide an
FFmpeg executable on PATH. PNG export needs no additional package.
See the [acceptance report](docs/ACCEPTANCE.md) for verified behavior and
remaining hardware checks.

CSV, Prophesee DAT (versions 1/2, CD events), and HDF5 event recordings open
through bundled Windows readers. No WSL, OpenEB, or camera SDK is needed for
file import. HDF5 supports integer `t,x,y,p` datasets under `CD/events` or
`events`, including Prophesee ECF compression and standard HDF5 compression.
Precomputed event cubes, histograms and time surfaces are not event recordings.
Live cameras still require the separately installed native SDK and driver.

## Workflow

Projects **save automatically when you close the editor**, including the session,
thumbnail and animated preview. `Ctrl+S` saves at any time. A failed save keeps
the editor open. There are no periodic recovery snapshots; save during longer
sessions to protect work against a crash or forced termination.
Use **File → Export portable project**
to create an `.ebs` bundle, with or without the loaded CSV recording.
Use **Import project** on the starting screen to bring it onto another computer.
See [saving and portable projects](docs/PROJECTS.md).

1. Create or open a project in the browser.
2. Use **File → Open recording** (`Ctrl+O`) for DAT, CSV, H5, or HDF5 files.
   DAT/HDF5 files are decoded locally without external tools. Large
   recordings offer a quick preview or full loading in a background thread.
   Converted imports use separate output
   directories so recordings with identical names cannot overwrite each other.
3. Scrub the timeline, or enter exact integer **Start µs** and **End µs** and
   apply the interval. End timestamps are exclusive. Adjust accumulation in
   milliseconds, down to one microsecond. **Zoom to interval** magnifies the
   current interval; **Full timeline** restores the recording's range.
4. **Step back/forward** and Left/Right use the configured microsecond step.
   Playback advances that same fixed step per requested 33 ms timer tick.
   Slow rendering affects wall-clock speed, not which dataset timestamps are
   visited. Playback is not a real-time acquisition clock.
5. Drag on either image to create a candidate rectangular ROI, then add/name
   it. Select a probe to move/resize it. Probe visibility, colors, duplication,
   and independent exports are available. The statistics table compares all
   probes in the current interval with the selected polarity filter.
6. Save the current interval as a slice. Slices capture exact bounds, polarity,
   source hash, stable IDs, and a snapshot of the active ROI. ROI edits or
   deletion do not alter that saved spatial selection. To change a slice's
   interval/polarity, apply an exact interval and use **Use exact current
   interval for selected slice**. The original spatial snapshot stays intact.
7. Export the full recording, an ROI, a slice, or the current interval plus
   active ROI. CSV contains original `t,x,y,p` integers, without rebasing or
   rendering effects. A JSON sidecar records selection bounds, source SHA-256,
   counts, timestamp units, sensor dimensions, and the CSV hash. Full/ROI
   exports are unfiltered; current-selection and slice exports use their
   explicit polarity constraints. Source recordings cannot be export targets.
8. **Ctrl+S** saves the project, thumbnail, and animated previews. **Save
   Session As** and **Load Session** also support standalone JSON sessions.

Polarity filtering is reversible: `both` shows all events, `pos` selects
positive events, and `neg` selects zero/negative polarity. Window statistics
and new slices follow it. Source arrays remain unchanged. The separate ROI
analysis panel explicitly displays unfiltered full-recording/current-window
analysis and discloses its presentation sampling.
The positive/negative ratio displays `inf` for positive-only selections and
uses zero for an empty selection; counts remain visible beside the ratio.
Optional refractory, prior-neighbor-support, and hot-pixel filters are available
in the analysis workspace. The main view and its window/probe statistics use
the derived view; the separate legacy ROI analysis panel stays explicitly
unfiltered. New slices capture filter parameters, and filtered exports retain
their DERIVED classification when reloaded with their metadata sidecar.

## Scientific and Studio views

| View | Classification | Rendering |
| --- | --- | --- |
| RAW | RAW | Actual event presence; positive orange, negative blue, mixed white; no intensity normalization |
| Persistence Trails | DERIVED | Most recent real event per pixel/polarity fades linearly over the specified duration, ending at the interval's exclusive end |
| Density Heatmap | DERIVED | Counts over the current interval; selectable log-relative, linear-relative, or fixed 100-events/pixel scale |
| Polarity Glow | STYLIZED | Polarity presence with an explicit adjustable 5×5 spatial halo |
| TRAIL | DERIVED | Preserved legacy time-colored accumulation, log scaling and relative normalization |
| Motion Arrows | DERIVED | Local polarity-separated log-count patch matching, with texture, uniqueness and reverse-consistency checks; unresolved motion is omitted |

**Compare with unfiltered RAW** synchronizes both images on one dataset,
interval, and shared ROIs. It also provides before/after polarity-filter
comparison. Classification and transformation descriptions appear in the UI.
Rendering parameters never change event CSV exports.

## Data integrity and compatibility

- CSV with named `t,x,y,p` columns supports arbitrary column order. Legacy
  headerless CSV uses **x,y,p,t**, matching OpenEB output. No first event is
  discarded. Integers are parsed without an intermediate floating-point cast.
- Timestamps must be nonnegative, nondecreasing int64 values (the maximum
  int64 value is reserved so an exclusive end can be represented). Coordinates
  must be nonnegative and below 32768; polarity is -1, 0, or 1. Invalid input
  is rejected rather than silently repaired, sorted, or truncated.
- Loading uses the whole CSV by default. Programmatic preview limits are
  marked incomplete; exporting those previews is blocked.
- Sensor resolution comes from a recognized DAT header, an export sidecar,
  or explicitly entered dimensions under **File → Set sensor resolution**.
  Otherwise it is labeled **inferred from observed coordinates**: inactive
  sensor edges cannot be recovered from event coordinates alone. Rendering
  supports up to 16 megapixels.
- Session format 8 preserves exact position/duration, zoom, step, ROIs, slices,
  polarity filter, comparison state, sensor metadata, and visualization
  parameters, advanced analysis settings, filters, annotations, and detected
  intervals. Versions 1–7 remain readable, accounting for their old capped
  timeline and skipped headerless first row. New saves use version 8.
- Loading old sessions now loads the full recording. Old global statistics
  may change because the old implementation loaded at most two million
  events. Old slices acquire spatial snapshots during migration.
- Sessions reference the CSV on disk. If it is moved, update `source.csv_path`
  in the JSON. A saved source hash detects changed content and prevents an
  apparently successful restoration against a different recording.

## Verification

```powershell
.\.venv\Scripts\python.exe -B -m scripts.run_tests
```

The tests exercise exact integer timestamps, half-open query boundaries,
lossless exports, preview guards, read-only event arrays, polarity rendering,
decay, RGB saving, background operations, worker failures, ROI snapshots,
source mismatch detection, and legacy/new session restoration. Qt uses its
offscreen platform during tests. Each test module runs in its own process
to isolate Qt state and teardown. Test-only native crash handling writes
diagnostics under `artifacts/test-runs/` instead of opening a Windows error
dialog. Native faults and unhandled Qt callback errors fail the run, including
faults after unittest prints its results. Normal app launches are unaffected.

The real CARS CSV was loaded and exported/reloaded with **4,829,705 events**;
all timestamps, coordinates, and polarities matched exactly. The existing real
DAT recording also passed the WSL/OpenEB DAT → H5 → CSV pipeline with the same
event count. V2 adds synthetic frequency/displacement validation, workspace and
filter-session integration tests, and simulated camera recording/buffer tests.
Native Windows early audio stopping was verified after replacing the WAV media
pipeline with Qt's short-sound player; physical audible output remains untested.
Recordings currently reside in RAM. Offline V2 jobs support cooperative
cancellation, including native recording import. No hidden denoising or
automatic scientific interpretation is applied.
