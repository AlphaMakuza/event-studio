# Event-Based Studio for Windows

This is the unsigned 2.0.0rc1 release candidate, not a finalized public release.

Install the Microsoft Visual C++ v14 x64 Redistributable from Microsoft's
official page first if it is not already installed:
https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist
Microsoft's runtime is a prerequisite and is not redistributed in this ZIP.

Extract the entire ZIP into a folder you can access, then double-click
`Event-Based-Studio.exe`. Keep the `_internal` folder beside the executable.
Python is included; you do not need to install it. Do not run directly inside the ZIP.
Large CSV/HDF5 files offer Quick preview or Load full recording. A preview is
limited to the first 2 million events and is labelled until the full file loads.
Verified local array caches speed up subsequent opens. They live under
`data/import-cache` in the app's storage folder and can be deleted with the app
closed. Converted CSV recordings remain separately under `data/converted`;
keep these if your projects reference them.
If extraction is interrupted, cancel and extract again into a new empty folder
before launching. An incomplete `_internal` folder can prevent startup.

The intended first release target is Windows 10/11 x64. Clean-machine validation
is still pending. A 64-bit CPU and enough RAM for your complete recording are
required; recordings are loaded into memory.

Packaged builds store projects, converted recordings, and logs under
`%LOCALAPPDATA%/Event-Based Studio`. Removing the application folder does not
remove your projects. Back up this storage folder and original recordings.
Use `.ebs` project export with the recording included to transfer a project.
The optional `EVENT_STUDIO_HOME` environment variable overrides storage.

CSV analysis works without camera software. Live cameras require a compatible
native Metavision SDK and driver, installed separately. DAT/H5/HDF5 event recordings open with bundled native readers; WSL/OpenEB
are not needed. Precomputed HDF5 tensors are not supported as recordings.
The initial preview omits the standalone FFmpeg MP4 encoder; PNG export is
available. The unused FFmpeg, PDF, Virtual Keyboard, QML/Quick, and software
OpenGL components have been removed; startup audio uses native Windows support.

The application has no account, upload, or automatic update service. Local
project bundles can contain paths and annotation text: review before sharing.
Qt settings are stored separately in the current user's settings store.

If startup fails, check `logs/application.log` in the storage folder. When
reporting a problem, include the version from `BUILD-INFO.json`, Windows version,
steps to reproduce, and a log you have reviewed for sensitive information.
Do not send private recordings unless you choose to share them.

Third-party license texts and a version inventory are under
`_internal/release-docs/third-party`. The application is proprietary software:
copyright (c) 2026 Alpha Makuza. See `LICENSE.txt` and `THIRD-PARTY.md`.
You retain your rights in your data and exported projects. The startup music,
logo, and loading artwork were created by Alpha Makuza and are included under
the application's proprietary license. See `_internal/release-docs/ASSETS.md`.
