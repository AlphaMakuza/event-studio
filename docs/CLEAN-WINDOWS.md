# Clean Windows release check

Run on a new Windows 10/11 x64 PC or VM without developer Python, WSL, or the
camera SDK. A minimal PATH on a development computer is useful but does not
establish a clean-machine result. Windows Sandbox is not available in the
current execution environment; no clean-machine result has been claimed.
Install the official Microsoft Visual C++ v14 x64 Redistributable prerequisite
from Microsoft before running the application. Do not copy DLLs from this
development machine. Record the prerequisite version in the test report.

1. Transfer the final ZIP, checksum, and `scripts/check_clean_windows.ps1` to
   the clean computer. Verify the ZIP using `Get-FileHash -Algorithm SHA256`.
2. Extract to a path with spaces and non-ASCII characters, for example
   `C:\Release tests\Alpha é\Event-Based-Studio`. Keep that folder read-only
   to the test user if possible. User storage must remain writable.
3. Run the supplied PowerShell helper with `-ApplicationFolder` set to the
   extracted application and `-ReportFolder` set to a writable results folder.
   It runs native GUI, CSV, native DAT/HDF5/ECF import with external processes
   blocked, save-on-close, `.ebs` roundtrip, and PNG-write checks.
4. Launch normally. Confirm the logo appears, startup music finishes, and the
   browser opens. Switch both appearances and browser views. Open a CSV, add a
   note, close/reopen, and verify the actual project was saved. Also open supported
   DAT, H5 and HDF5 event files through the same picker without WSL/OpenEB.
   Use synthetic data first, then representative real recordings.
5. Export/import `.ebs` with and without its recording, relocate an identical
   CSV, and verify the note/ROI/interval. Export PNG via the normal menu.
6. Verify a missing camera SDK is explained; file import must not need it. Confirm projects and
   logs go to user storage and removing the app folder leaves data intact.
7. Record Windows edition/build, app/ZIP hashes, machine cleanliness, manual
   results, and tester/date in the generated report. Any failure blocks release.

The helper deliberately leaves `clean_machine_confirmed_by_tester` false and
manual interaction pending. A person must verify these facts. Optional camera
hardware integrations require separate real-hardware checks.
