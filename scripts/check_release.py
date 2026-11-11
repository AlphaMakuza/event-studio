"""Verify checksum, extract the download, and smoke-test its bundled GUI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--native", action="store_true", help="Use the native Windows Qt platform")
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    expected = archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()[0]
    with archive.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected, "Checksum mismatch"
    with tempfile.TemporaryDirectory(prefix="ebs-release-") as directory:
        root = Path(directory)
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                assert (root / name).resolve().is_relative_to(root.resolve()), "Unsafe archive path"
                assert len(name) <= 135, f"ZIP extraction path is too long: {name}"
            bundle.extractall(root)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        env["EVENT_STUDIO_HOME"] = str(root / "user storage")
        env["QT_QPA_PLATFORM"] = "windows" if args.native else "offscreen"
        executable = root / "Event-Based-Studio" / "Event-Based-Studio.exe"
        folder = executable.parent
        forbidden = ("qt6virtualkeyboard", "qt6pdf", "qt6quick", "qt6qml", "ffmpegmediaplugin", "avcodec-", "avformat-", "avutil-", "swscale-", "swresample-", "opengl32sw", "msvcp", "vcruntime", "concrt")
        unexpected = [str(p.relative_to(folder)) for p in folder.rglob("*.dll") if p.name.lower().startswith(forbidden)]
        assert not unexpected, f"Unused native libraries reappeared: {unexpected}"
        license_text = (folder / "LICENSE.txt").read_text(encoding="utf-8")
        assert "Alpha Makuza" in license_text and "Third-party software takes precedence" in license_text
        assert (folder / "THIRD-PARTY.md").is_file(), "Missing third-party notice"
        info = json.loads((folder / "BUILD-INFO.json").read_text(encoding="utf-8"))
        if info["approved_assets_included"]:
            source_assets = Path(__file__).resolve().parents[1] / "event_studio" / "assets"
            for name in ("boot.wav", "logo.png", "loading.png"):
                bundled = folder / "_internal" / "event_studio" / "assets" / name
                assert bundled.is_file(), f"Missing approved asset: {name}"
                assert hashlib.sha256(bundled.read_bytes()).digest() == hashlib.sha256((source_assets / name).read_bytes()).digest(), f"Asset differs from source: {name}"
            assert (folder / "_internal" / "release-docs" / "ASSETS.md").is_file(), "Missing asset ownership record"
        else:
            assert not (folder / "_internal" / "event_studio" / "assets").exists(), "Unapproved assets were bundled"
        result = subprocess.run([str(executable), "--smoke-test"], cwd=root, env=env,
                                capture_output=True, text=True, timeout=45)
        record = root / "user storage" / "smoke-test.json"
        if result.returncode or not record.exists():
            log = root / "user storage" / "logs" / "application.log"
            raise RuntimeError(f"Packaged launch failed ({result.returncode})\n{result.stdout}\n{result.stderr}\n"
                               + (log.read_text(encoding="utf-8") if log.exists() else "No application log"))
        report = json.loads(record.read_text())
        assert report["passed"] and report["frozen"], "Smoke test failed or used the development interpreter"
        assert "ebs roundtrip" in report["checks"], "Project transfer was not checked"
        print("PASS: ZIP checksum, license/notice inclusion, asset verification, extracted executable, isolated storage, browser/editor rendering.")
        print("Packaged functional checks: " + ", ".join(report["checks"]))
        print("Platform: " + env["QT_QPA_PLATFORM"] + "; clean-machine validation is a separate requirement.")


if __name__ == "__main__":
    main()
