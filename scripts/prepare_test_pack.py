"""Create a transferable clean-Windows test pack; no Python needed on that PC."""
import hashlib
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    stage = ROOT / "artifacts" / "windows-test-pack"
    stage.mkdir(parents=True, exist_ok=True)
    application = stage / "Event-Based-Studio"
    if application.exists():
        assert application.resolve().is_relative_to(stage.resolve())
        shutil.rmtree(application)
    shutil.copytree(ROOT / "dist" / "Event-Based-Studio", stage / "Event-Based-Studio", dirs_exist_ok=True)
    shutil.copy2(ROOT / "scripts" / "check_clean_windows.ps1", stage / "check_clean_windows.ps1")
    shutil.copy2(ROOT / "docs" / "CLEAN-WINDOWS.md", stage / "MANUAL-CHECKLIST.md")
    (stage / "Run-Windows-Check.cmd").write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_clean_windows.ps1" -ApplicationFolder "%~dp0Event-Based-Studio" -ReportFolder "%~dp0Results"\r\npause\r\n', encoding="ascii")
    (stage / "START-HERE.txt").write_text(
        "Event-Based Studio 2.0.0rc1 - clean Windows test pack\n\n"
        "1. Copy this ZIP to the clean Windows x64 PC/VM and extract it fully.\n"
        "2. Install the official Microsoft Visual C++ v14 x64 runtime first:\n"
        "   https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist\n"
        "3. Double-click Run-Windows-Check.cmd. It runs the local test script with\n"
        "   a process-only PowerShell policy setting; it does not change system policy.\n"
        "   No Python, camera SDK, or WSL installation is needed.\n"
        "4. The automated check takes about 15 seconds. Look for PASS.\n"
        "5. Follow MANUAL-CHECKLIST.md, including audible startup music and recovery.\n"
        "6. In Results/windows-check-*.json, record clean_machine_confirmed_by_tester\n"
        "   as true only for a clean PC/VM; set manual_startup_audio_and_interaction\n"
        "   to passed only after those checks pass. Include any failures and notes.\n"
        "7. Return that JSON report and a description of any problem. Logs are local\n"
        "   under Results/user data-*/logs. Review before sharing.\n\n"
        "This build is unsigned. Signing is optional; final release awaits these\n"
        "clean-machine and manual checks. Use synthetic data or copies of recordings.\n",
        encoding="utf-8")
    archive = Path(shutil.make_archive(str(ROOT / "artifacts" / "Event-Based-Studio-2.0.0rc1-Windows-Test-Pack"), "zip", stage))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
