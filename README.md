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

The homepage offers **Image + text**, **Text only**, and **Large tiles** views,
with project/dataset search and sorting by name or last save. Your view choice
is remembered. Startup shows the transparent logo and retro loading label;
the homepage opens when the startup song finishes, with a fallback if audio
cannot play.

## Run

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

CSV exploration requires only the Python dependencies. DAT/H5 conversion also
requires WSL and OpenEB's `metavision_file_to_hdf5` and
`metavision_file_to_csv`. The converter probes the existing OpenEB build paths
under the WSL user's home. `WSL_DISTRO` in `event_studio/convert.py` can select
a distribution; otherwise WSL's default is used.

## Workflow

1. Create or open a project in the browser.
2. Use **File → Import .dat** or **Open CSV / H5**. Imports load the complete
   recording in a background thread. Converted imports use separate output
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
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

The tests exercise exact integer timestamps, half-open query boundaries,
lossless exports, preview guards, read-only event arrays, polarity rendering,
decay, RGB saving, background operations, worker failures, ROI snapshots,
source mismatch detection, and legacy/new session restoration. Qt uses its
offscreen platform during tests.

The real CARS CSV was loaded and exported/reloaded with **4,829,705 events**;
all timestamps, coordinates, and polarities matched exactly. The existing real
DAT recording also passed the WSL/OpenEB DAT → H5 → CSV pipeline with the same
event count. V2 adds synthetic frequency/displacement validation, workspace and
filter-session integration tests, and simulated camera recording/buffer tests.
Native Windows early audio stopping was verified after replacing the WAV media
pipeline with Qt's short-sound player; physical audible output remains untested.
Recordings currently reside in RAM. Offline V2 jobs support cooperative
cancellation; running OpenEB conversion jobs do not. No hidden denoising or
automatic scientific interpretation is applied.
