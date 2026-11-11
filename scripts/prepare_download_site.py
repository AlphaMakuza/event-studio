"""Prepare a static review website with checksum-verified, size-bounded downloads."""
import hashlib
import json
from pathlib import Path
import shutil

from event_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def main():
    site = ROOT / "website" / "dist"
    documents = site / "documents"
    downloads = site / "downloads"
    documents.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)
    for name in ("DOWNLOAD", "PRIVACY", "SUPPORT", "THIRD-PARTY", "RELEASE-NOTES", "ASSETS", "DEPENDENCY-AUDIT"):
        shutil.copy2(ROOT / "docs" / f"{name}.md", documents / f"{name}.txt")
    shutil.copy2(ROOT / "LICENSE.txt", documents / "LICENSE.txt")
    sources = ROOT / "artifacts" / "Event-Based-Studio-Qt-6.10.1-corresponding-source.zip"
    application = ROOT / "dist" / f"Event-Based-Studio-{__version__}-windows-x64-preview.zip"
    manifest = {}
    sums = []
    for key, label, source in (("application", "Windows release candidate", application), ("source", "Qt/PySide corresponding source", sources)):
        parts = []
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            number = 1
            while data := stream.read(16 * 1024 * 1024):
                digest.update(data)
                target = downloads / f"{key}-{number:02d}.part"
                target.write_bytes(data)
                parts.append(f"downloads/{target.name}")
                number += 1
        manifest[key] = {"label": label, "filename": source.name, "sha256": digest.hexdigest(), "parts": parts, "size": source.stat().st_size}
        sums.append(f"{digest.hexdigest()}  {source.name}")
    (downloads / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (documents / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="ascii")
    # Reassemble each hosted set to verify the exact bytes served to browsers.
    for item in manifest.values():
        digest = hashlib.sha256()
        for part in item["parts"]:
            digest.update((site / part).read_bytes())
        assert digest.hexdigest() == item["sha256"]
    print("PASS: website documents, binary/source download parts, and reassembled SHA-256.")


if __name__ == "__main__":
    main()
