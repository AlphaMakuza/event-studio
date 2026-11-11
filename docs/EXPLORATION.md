# Recording exploration tools

The dark violet interface and square controls remain unchanged. These tools
work on offline recordings; live acquisition still requires hardware validation.

| Tool | Where | Behavior |
| --- | --- | --- |
| Recording overview | Above the playback controls | At most 512 exact activity bins, aligned with timeline zoom. Click or drag to seek without changing frame duration. |
| Linked activity plots | ROI Analysis activity graph; Advanced Analysis Activity tab | Click to seek playback. Drag across time to name and save a slice. |
| ROI comparison | Analysis > Compare ROI activity | Compares all named ROIs across the full recording, initially normalized to events/ms/pixel. Advanced Analysis can change scope, interval, polarity and bin width. |
| Diagnostics | Analysis > Recording quality diagnostics | Original loaded events, independently of display filters. Configurable high-rate pixel, event-free gap, and prior-neighbor support thresholds. Export JSON; double-click a gap to inspect it. |
| Batch comparison | Analysis > Batch analyze recordings | Opens batch settings in Advanced Analysis. Select CSV recordings and an output parent directory. Results appear in a table and in CSV/JSON exports. |
| Undo / redo | Edit menu; Ctrl+Z / Ctrl+Shift+Z or Ctrl+Y | Up to 100 ROI and slice edits, including additions, deletion, names, colors, visibility, bounds, movement, and loop changes. A drag is one edit. |

## Measurement and selection behavior

- Time bounds are integer microseconds and intervals are `[start, end)`.
  Plots use relative milliseconds so large source timestamps retain precision.
  Clicking a plot or overview pauses playback to inspect the selected moment.
- The overview uses every loaded event and does not follow display filters or
  polarity selection. It follows timeline zoom. Its height and color show the
  logarithmic bin rate, without an interval overlay. It is a
  navigation aid, not an audio waveform or calibrated sensor-quality measure.
- Saved slices are shown and edited on the bottom time bar. Jumping to a slice
  preserves frame duration rather than accumulating its whole interval into
  one frame. Use the 20 ms frame button to reduce motion trails from a long
  frame window; Apply interval remains available for explicit accumulation.
- Advanced Analysis plot slices capture that graph's saved filter and polarity
  settings. A single-probe graph also captures its ROI. Spans on multi-probe
  comparisons are temporal selections over the full field.
- The separate ROI activity graph remains unfiltered. A slice drawn there
  captures that graph's ROI and unfiltered polarity settings, even if the main
  viewer is displaying filtered events. Reloading a source closes old ROI graphs.
- Normalized comparison rate is `events / actual bin duration in ms / ROI area
  in pixels`. The partial final bin uses its actual duration. CSV exports include
  both absolute and per-pixel rates. Per-pixel rates allow comparison by area;
  they do not account for sensor sensitivity or scene differences.
- Batch analysis reuses bin width, burst threshold, minimum burst duration,
  polarity, and current explicit filters. Reusing named ROIs requires verified
  matching sensor dimensions; inferred dimensions are insufficient. Each source
  gets its own full-recording interval. Errors and cancellation are retained in
  the report; completed results are not silently discarded. The summary includes
  ROI area and rate per pixel.

## Diagnostic interpretation

High-rate pixels exceed the chosen events/ms threshold over the loaded recording.
Gaps are consecutive-event timestamp differences at least the chosen threshold.
Neither observation alone proves a defective pixel or dropped acquisition data.

The unsupported-event fraction counts events without an **earlier** event from a
different pixel in the 3x3 neighborhood within the selected interval. It uses the
same explicit causal support rule as the existing support filter. Startup events,
sparse scenes, and isolated real motion can all be unsupported. This is a
background-activity proxy, not a calibrated noise estimate. Nothing is removed
from the recording. Diagnostics run in a cancellable background task.

The report includes polarity counts, positive fraction, active pixels, event rate,
same-timestamp pairs, all threshold values, source metadata, and at most 100
highest-rate pixels and 100 largest gaps. Counts describe the full loaded data;
only the displayed/exported detail tables are capped. Source timestamps may have
been sorted by the importer, so original arrival-order problems cannot always be
reconstructed. A loaded subset or derived recording is not the original acquisition.

## History limits

History stores editing state, not event arrays, and does not rewrite source data.
ROI deletion and undo preserve slice IDs and saved spatial snapshots. Loading or
resetting a recording clears history. History is not saved inside sessions.
Opening dialogs, cancelling edits, seeking, playback, import, project deletion,
and file exports are not undoable edits. Undo does not delete exported files.
