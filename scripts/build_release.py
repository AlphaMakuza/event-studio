"""Build an unsigned Windows preview ZIP; never publishes a release."""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from event_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def dependency_notices(destination):
    """Retain installed license texts and exact runtime dependency versions."""
    pending = ["numpy", "h5py", "PySide6", "matplotlib", "qtawesome", "PyInstaller"]
    seen = set()
    inventory = []
    while pending:
        name = pending.pop()
        key = canonicalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        dist = metadata.distribution(name)
        item = {"name": dist.metadata["Name"], "version": dist.version,
                "license": dist.metadata.get("License-Expression") or dist.metadata.get("License", "See bundled license texts"),
                "license_files": []}
        for file in dist.files or []:
            if any(token in str(file).lower() for token in ("license", "copying", "notice", "copyright")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    # Keep package-relative paths while preventing metadata paths escaping output.
                    parts = [p for p in file.parts if p not in ("..", ".")]
                    target = destination / key / Path(*parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    item["license_files"].append(str(target.relative_to(destination)))
        inventory.append(item)
        for value in dist.requires or []:
            req = Requirement(value)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                pending.append(req.name)
    destination.mkdir(parents=True, exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, destination / "PYTHON-LICENSE.txt")
    (destination / "inventory.json").write_text(json.dumps(sorted(inventory, key=lambda x: x["name"]), indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-approved-assets", action="store_true", help="Include artwork and audio only after confirming redistribution rights")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("Build this Windows x64 download on Windows x64.")
    name = "Event-Based-Studio"
    # Exclude optional encoder even if a developer installed it locally; adding
    # FFmpeg requires its own binary/license review and an updated inventory.
    stage = ROOT / "build" / "release-docs"
    notices = stage / "third-party"
    dependency_notices(notices)
    for document in ("DOWNLOAD.md", "RELEASE.md", "THIRD-PARTY.md", "ASSETS.md", "DEPENDENCY-AUDIT.md"):
        shutil.copy2(ROOT / "docs" / document, stage / document)
    shutil.copy2(ROOT / "LICENSE.txt", stage / "LICENSE.txt")
    legal = ROOT / "docs" / "legal"
    if legal.exists():
        shutil.copytree(legal, stage / "legal", dirs_exist_ok=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm",
               "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"),
               str(ROOT / "scripts" / "release.spec")]
    env = dict(os.environ)
    env["EVENT_STUDIO_BUILD_ASSETS"] = "1" if args.include_approved_assets else "0"
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    folder = ROOT / "dist" / name
    from scripts.runtime_imports import retarget_private_msvc
    modifications = retarget_private_msvc(folder)
    (folder / "RUNTIME-IMPORT-CHANGES.json").write_text(json.dumps(modifications, indent=2), encoding="utf-8")
    shutil.copy2(ROOT / "docs" / "DOWNLOAD.md", folder / "START-HERE.md")
    shutil.copy2(ROOT / "LICENSE.txt", folder / "LICENSE.txt")
    shutil.copy2(ROOT / "docs" / "THIRD-PARTY.md", folder / "THIRD-PARTY.md")
    for document in ("PRIVACY.md", "RELEASE-NOTES.md", "SUPPORT.md"):
        if (ROOT / "docs" / document).exists():
            shutil.copy2(ROOT / "docs" / document, folder / document)
    with (folder / "BUILD-ENVIRONMENT.txt").open("w", encoding="utf-8") as stream:
        subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], check=True, stdout=stream)
    native = [{"path": str(p.relative_to(folder)).replace("\\", "/"),
               "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
              for p in sorted(folder.rglob("*.dll"))]
    (folder / "NATIVE-LIBRARIES.json").write_text(json.dumps(native, indent=2), encoding="utf-8")
    (folder / "BUILD-INFO.json").write_text(json.dumps({"version": __version__, "python": sys.version,
        "platform": platform.platform(), "approved_assets_included": args.include_approved_assets,
        "release_status": "unsigned internal preview; legal and clean-machine checks pending"}, indent=2), encoding="utf-8")
    from scripts.package_release import package
    archive = package()
    print(f"Preview download: {archive}")


if __name__ == "__main__":
    main()
