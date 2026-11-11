"""Package an existing folder, preserving a signed executable if present."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def package():
    folder = ROOT / "dist" / "Event-Based-Studio"
    from scripts.short_release_paths import shorten_dependencies, shorten_notices
    shorten_notices(folder)
    shorten_dependencies(folder)
    info_path = folder / "BUILD-INFO.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    executable = folder / "Event-Based-Studio.exe"
    signature = subprocess.run(["powershell", "-NoProfile", "-Command",
        f"(Get-AuthenticodeSignature -LiteralPath '{str(executable).replace(chr(39), chr(39)*2)}').Status.ToString()"],
        check=True, capture_output=True, text=True).stdout.strip()
    info["authenticode_status"] = signature
    info["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    info["publisher"] = "Alpha Makuza"
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    for name in ("DOWNLOAD", "RELEASE", "THIRD-PARTY", "ASSETS", "DEPENDENCY-AUDIT"):
        shutil.copy2(ROOT / "docs" / f"{name}.md", folder / "_internal" / "release-docs" / f"{name}.md")
    for name in ("PRIVACY", "RELEASE-NOTES", "SUPPORT", "THIRD-PARTY"):
        shutil.copy2(ROOT / "docs" / f"{name}.md", folder / f"{name}.md")
    shutil.copy2(ROOT / "docs" / "DOWNLOAD.md", folder / "START-HERE.md")
    # Reserve room for Downloads plus Explorer's automatically named ZIP folder.
    longest = max(len(str(p.relative_to(ROOT / "dist"))) for p in folder.rglob("*") if p.is_file())
    assert longest <= 135, f"Release paths are too long for normal extraction: {longest}"
    archive = Path(shutil.make_archive(str(ROOT / "dist" / f"Event-Based-Studio-{info['version']}-windows-x64-preview"), "zip", ROOT / "dist", folder.name))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Packaged {archive} (Authenticode: {signature})")
    return archive


if __name__ == "__main__":
    package()
