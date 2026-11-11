"""Report public launch gates without mistaking a candidate build for approval."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
    executable = ROOT / "dist" / "Event-Based-Studio" / "Event-Based-Studio.exe"
    blockers = []
    if not config["support_contact"]:
        blockers.append("Publisher support email or URL is missing.")
    signature = subprocess.run(["powershell", "-NoProfile", "-Command",
        f"(Get-AuthenticodeSignature -LiteralPath '{str(executable).replace(chr(39), chr(39)*2)}').Status.ToString()"],
        capture_output=True, text=True, check=True).stdout.strip()
    if signature != "Valid" and config.get("require_signature", False):
        blockers.append(f"Publisher Authenticode signature is {signature}.")
    elif signature != "Valid":
        print(f"INFO: Authenticode is {signature}; unsigned distribution must remain clearly disclosed.")
    report_path = config["clean_windows_report"]
    if not report_path:
        blockers.append("No confirmed clean-Windows/manual interaction report.")
    else:
        report = json.loads((ROOT / report_path).read_text(encoding="utf-8-sig"))
        actual = hashlib.sha256(executable.read_bytes()).hexdigest()
        if not (report.get("clean_machine_confirmed_by_tester") and report.get("functional_checks_passed")
                and report.get("manual_startup_audio_and_interaction") == "passed"
                and report.get("executable_sha256", "").lower() == actual):
            blockers.append("Clean-Windows report is incomplete or tests a different executable.")
    if not (ROOT / config["source_companion"]).is_file():
        blockers.append("Matching corresponding-source companion is missing.")
    if config["release_stage"] != "stable" or not config["public_release_checks_complete"]:
        blockers.append("Release is still a candidate; final public checks are incomplete.")
    for reason in blockers:
        print("PENDING: " + reason)
    if blockers:
        raise SystemExit(1)
    print("PASS: public release gates recorded.")


if __name__ == "__main__":
    main()
