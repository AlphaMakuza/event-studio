# Event-Based Studio 2.0.0rc1

Release candidate — November 10, 2026. Publisher: Alpha Makuza.

## Included

- Portable Windows file import for Prophesee DAT v1/v2 CD recordings and
  integer HDF5 event datasets, including ECF-compressed files. No WSL/OpenEB
  installation is needed. Large files offer preview and full-load options.

- Notes are simple comments below the playback scrubber. Click their timeline
  markers to read, edit, delete, or seek without changing frame duration.
  Advanced Analysis lists all notes and timeframes with jump and export actions;
  existing interval notes and project storage remain compatible.
- Refresh View redraws the recording and resets timeline zoom without clearing
  the recording, ROIs, slices, filters, annotations, frame settings, or undo history.
- Advanced Analysis opens on the full recording, with slice-specific analysis
  available from either slice context menu. Each tab has a short explanation.
- Motion controls use plain-language labels and explanatory tooltips. Numeric
  controls have visible step arrows in both themes, and secondary windows and
  Qt dialogs share the Studio title bar.
- The top activity bar has no interval overlay. Saved-slice navigation preserves
  frame duration, and a 20 ms frame reset helps reduce motion trails.
- A thin activity-bar playhead follows playback and scrubbing, aligned with
  the bottom time slider.
- The recording activity bar smoothly blends blue, cyan, green, violet, and
  hot pink as activity increases, using the recording's logarithmic scale.
- Studio View descriptions and slice details use plain language, with technical
  rendering details available in tooltips.
- The activity bar and playback slider share their visible time range and align
  horizontally, including after zooming or resizing. Saved slices use a separate
  editing row so they do not intercept playback scrubbing.
- Large CSV/HDF5 recordings offer a quick preview of the first 2 million events,
  followed by an explicit full-load action. Partial previews stay labelled and
  cannot be exported as full recordings or portable project bundles.
- Local checksum-validated array caches speed up reopening recordings and projects.
- The activity overview seeks without changing frame duration or creating slices.
  Saved slices use right-click actions and support the Delete key.
  View > Timeline contains Zoom to window and Reset timeline zoom; the bottom
  bar keeps playback, stepping, and interval controls.
- CSV/HDF5 imports show conversion and parsing stages, event counts, and a Cancel
  button. Numeric CSV parsing uses compact blocks to reduce loading time and
  temporary memory. HDF5 event recordings accept both `.h5` and `.hdf5`.
- Local CSV event-recording exploration, interval/ROI analysis, annotations,
  filtering, diagnostics, overview plots, and undo/redo.
- Automatic project saving on close, including the thumbnail and animated preview.
- Portable `.ebs` export/import, with optional recording inclusion and checksums.
- Glass and Original appearances and original startup artwork/music.
- A portable Windows x64 folder bundle with Python included, local error logs,
  proprietary application terms, and separate third-party notices.

## Requirements and limitations

- Target: Windows 10/11 x64. Recordings are loaded into RAM; capacity depends
  on recording size and available memory. This release candidate is not yet
  certified on a clean computer.
- Requires Microsoft's Visual C++ v14 x64 runtime, installed separately from
  Microsoft. Python is included; no developer Python installation is required.
- CSV analysis and PNG output are included. The standalone MP4 encoder is not
  bundled; MP4 requires a separately installed compatible FFmpeg executable.
- Live acquisition requires the native Metavision SDK and compatible drivers.
  DAT/H5/HDF5 event files use bundled readers, including ECF decompression;
  no WSL, OpenEB or camera SDK is needed for file import. Precomputed HDF5
  tensors are not event recordings. Hardware integrations remain separate.
- Closing normally saves the project. Unsaved text in open forms and changes
  since the last successful save may be lost after a crash or forced termination.
- The candidate is unsigned until the publisher supplies signing access.
  The download must disclose its unsigned status. Signing can be added later.
  Clean-machine checks must be complete before final public release. Direct
  email assistance is not available; use the website troubleshooting page.
  No automatic update mechanism is included.

## Installation and upgrades

Extract the whole ZIP and run `Event-Based-Studio.exe`. Keep `_internal` beside
it. Back up projects before upgrading. Packaged builds use a user storage
folder; existing source-checkout projects are not automatically moved there.
Use `.ebs` export/import to transfer them. Removing the app does not remove
user projects. See START-HERE.md, PRIVACY.md, and LICENSE.txt in the download.
