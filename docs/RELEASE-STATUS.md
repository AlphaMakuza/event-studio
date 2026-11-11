# Release status ? November 10, 2026

Prepared version: **2.0.0rc1**, proprietary, copyright 2026 Alpha Makuza.
Original startup music and artwork are included with the author's authorization.

## Completed locally

- Windows x64 folder bundle, Python included, writable user storage, local logs,
  original branding, and an About/licenses/privacy dialog.
- Full automated suite passed (12 modules); homepage/GUI checks passed again
  after adding the About entry points.
- Packaged native-Windows checks passed: startup overlay/audio completion or
  fallback, browser/editor, both appearances, NumPy FFT, CSV loading, recovery,
  `.ebs` transfer, and PNG writing. This is a development PC result, not a claim
  of audible playback, full manual interaction, or clean-machine validation.
- Removed unused GPL-only Virtual Keyboard, PDF, FFmpeg, QML/Quick, and Mesa
  software OpenGL paths. Microsoft runtime DLLs are omitted; the official x64
  runtime is an explicit prerequisite. NumPy's private runtime imports are
  retargeted and the changes/hashes disclosed in the bundle.
- Full Qt license texts, source notices, font notices/attributions, dependency
  inventory, native-library hashes, and build-environment inventory included.
- Exact Qt/PySide 6.10.1 source companion prepared with checksums and build and
  library-replacement instructions.
- Privacy information, release notes, installation/support guidance, signing
  and clean-Windows test helpers, and release-readiness checks prepared.
- Responsive download website prepared with a synthetic-data screenshot,
  application/source downloads, and browser-side SHA-256 verification. Local
  asset/link and download/corruption-rejection checks passed. No browser QA
  tool is available here; responsive browser review remains appropriate.
- Transferable clean-Windows test pack includes the app, one-click test runner,
  and a manual checklist. The publisher has a clean PC/VM available.

## Remaining

1. Run the test pack on the publisher's clean Windows PC/VM and return the
   generated report plus manual results. No clean-machine pass is recorded yet.
2. After the candidate passes, select stable version metadata, rebuild/retest,
   update website/checksums, and make the download website public.

Private Sites deployment succeeded:
https://event-based-studio-alpha-makuza.luxedance1.chatgpt.site

It includes the candidate binary and matching corresponding-source download.
The staging project/version/deployment and source commit are recorded in
release.json. This is private staging, not the final public launch.

Signing is recommended, not mandatory. No signing certificate or SignTool is
available here. Current policy permits clearly disclosed unsigned distribution.
The website provides self-service troubleshooting; direct support email/ticket
submission is not available. No email address was invented.
