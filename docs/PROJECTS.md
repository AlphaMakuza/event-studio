# Saving and portable projects

These features work locally. No account, server, or upload is involved.

## Save automatically on close

Closing the editor with X saves the actual project session, thumbnail and
animated preview. Ctrl+S saves at any time. A standalone editor with a loaded
recording creates a project automatically when closed. Empty editors do not
create projects. Finish an import/export before closing.

Saving includes committed intervals, view settings, ROIs, slices, filters,
annotations, detections and analysis settings. Commit text in a dialog or form
with its Add/Update button first. Source recordings are not modified.
If saving fails, the editor stays open and reports the error.

There are no periodic recovery snapshots or recovery menu actions. Closing
normally saves your work; a crash, forced termination or power loss can lose
changes made since the last successful save. Use Ctrl+S during longer sessions.
Older snapshots are restored automatically when available and are cleared after
a successful normal save, preserving work from previous versions.

Missing recordings can be located through a file picker; their SHA-256 must
match the saved session. Closing the editor or pressing Ctrl+S saves the updated
recording reference.

## Export a portable project

1. Open the project and choose **File → Export portable project…**.
2. Leave **Include recording for use on another computer** checked for a
   self-contained transfer. This includes the loaded CSV and its metadata
   sidecar, not the original DAT/H5 file or unrelated files in the project.
3. Choose a destination ending in `.ebs`.

The bundle contains a snapshot of the current session, including unsaved
committed edits, plus available thumbnail and preview images. Those images
come from the last normal project save; exporting does not regenerate them.
Save normally first if you want updated previews. Exporting itself does not
commit the project's normal save or close the editor.

Uncheck the recording option for a smaller bundle. The recipient must have
an identical CSV and locate it when opening the imported project. The app
checks its checksum; a different recording cannot silently inherit the analysis.

The bundle retains provenance metadata, which can contain original file paths
and annotation text. Review that information before sharing with other people.

## Import on another computer

1. Transfer the `.ebs` file by USB or a storage service of your choice.
2. On the starting screen, click **Import project** and select the bundle.
   Older `.evstudio` bundles are also accepted.
3. Open the newly imported project. If the recording was omitted, locate it
   when prompted. Press `Ctrl+S` to save the new reference.

Import always creates a new project folder, adding a numeric suffix on a name
collision. Included recordings use relative paths, so their project folders
can also be moved later. Import/export run in background tasks and can be
cancelled. Failed/cancelled exports retain an existing destination bundle;
failed/cancelled imports do not publish partial projects.

## Bundle format and limits

`.ebs` is a ZIP archive with a version-1 manifest, per-file SHA-256 and
size checks, a version-8 session, metadata, optional images, and optionally
`recording/events.csv` plus `recording/events.json`. Checksums detect corruption;
they are not publisher signatures. Bundles from other people remain untrusted.

Imports reject path traversal, absolute paths, unexpected files, links,
encryption, duplicate names, inconsistent manifests, and invalid source identity.
Extraction is streamed into a staging folder before publication. The current
limit is 64 GiB uncompressed, 10,000 files, and 16 MiB per JSON document, with
an additional available-disk-space check. Recordings are still loaded into RAM
when opened; portable bundles do not remove that existing memory limit.
