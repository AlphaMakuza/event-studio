# Release preparation

## Build an internal Windows preview

From the repository root, in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m scripts.run_tests
.\.venv\Scripts\python.exe -m scripts.build_release --include-approved-assets
.\.venv\Scripts\python.exe -m scripts.check_release dist/Event-Based-Studio-2.0.0rc1-windows-x64-preview.zip
```

Output: `dist/Event-Based-Studio-<version>-windows-x64-preview.zip`, SHA-256
file, and an unpacked application directory. Build on Windows x64. This is a
folder bundle so libraries remain separate. The build copies runtime dependency
license texts and exact version metadata; this inventory does not by itself
establish redistribution compliance. No recordings, projects, SDK, standalone MP4 encoder,
credentials, or repository metadata are intentionally bundled.
The tracked release.spec removes unused FFmpeg, PDF, Virtual Keyboard, QML/Quick,
Mesa software-OpenGL, and Microsoft runtime DLLs. Users install Microsoft's
official x64 C++ runtime prerequisite. The package checker rejects reintroduction.

Alpha Makuza confirmed ownership of the startup music, logo, and loading artwork.
Use `--include-approved-assets` for the branded build; see ASSETS.md for the record.
Omitting that flag still produces an unbranded build.
Build dependencies are bounded but not fully locked; preserve the build environment
and generated inventory when producing a public version.

## Public release gates

- Application license: proprietary, copyright 2026 Alpha Makuza; `LICENSE.txt`
  is included in the download. The website provides self-service support;
  direct email assistance is not available yet.
- Startup music, logo, and loading artwork are approved first-party assets,
  copyright 2026 Alpha Makuza. Recheck permissions for any future additions.
- Review every bundled dependency and Qt plugin's actual license. Retain notices,
  provide corresponding source and any installation/replacement information
  required by the selected licenses. Verify QtAwesome's bundled font licenses too.
  PySide6/Qt license obligations are separate from the application license.
- Audit the generated bundle for unexpected libraries/files and license gaps;
  inventory metadata is a starting point, not an automated legal clearance.
- Verify the local privacy statements against the final binary and dependencies.
- Pass all automated tests, then test the extracted download on a clean Windows
  x64 computer without Python, developer tools, SDK, or WSL. Verify launch,
  both appearance modes, CSV loading, saving/recovery, `.ebs` export/import,
  PNG export, missing optional dependencies, and closing without data loss.
- Test paths with spaces/non-ASCII characters and a read-only application directory.
- Verify DAT/HDF5/ECF file import in the extracted bundle with external processes
  blocked. Run a real camera/SDK check before advertising camera integrations.
- Choose a public version and produce release notes with known limits. The
  current policy allows an explicitly unsigned release. Signing is recommended
  when the publisher obtains a certificate/service; it is not a prerequisite.
  After signing, repackage without rebuilding the EXE and regenerate SHA-256.
- Add the verified ZIP, checksum, system requirements, support contact, license,
  privacy information, and release notes to the download website.

An installer and `.ebs` file association can follow the portable release. Never
remove user projects during an uninstall. Public publishing is a separate step.

## Primary references

- Qt for Python licensing: https://doc.qt.io/qtforpython-6/
- Qt LGPL obligations: https://www.qt.io/licensing/open-source-lgpl-obligations
- PyInstaller operation: https://pyinstaller.org/en/stable/operating-mode.html
- PyInstaller license exception: https://pyinstaller.org/en/stable/license.html
