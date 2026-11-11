"""Portable, checksummed project archives, with staged and bounded import."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

from PySide6.QtCore import QLockFile
from .project_utils import now_iso, sanitize_project_name, save_json, unique_project_dir
from .recovery import resolve_session_source
from .session_validation import validate_settings

EXTENSION = ".ebs"
IMPORT_FILTER = "Event-Based Studio project (*.ebs *.evstudio)"
MAX_JSON = 16 * 1024 * 1024
MAX_FILES = 10000
MAX_BYTES = 64 * 1024**3
CHUNK = 1024 * 1024


def _check_cancel(cancel):
    if cancel and cancel():
        from .filters import CancelledError
        raise CancelledError("Project transfer cancelled. Existing files were kept.")


def _json_bytes(value):
    return json.dumps(value, indent=2, allow_nan=False).encode("utf-8")


def _source_hash(path, cancel, progress):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(CHUNK):
            _check_cancel(cancel)
            digest.update(chunk)
            if progress:
                progress(0, "Verifying source recording…")
    return digest.hexdigest()


def _allowed(name):
    return name in ("session.json", "metadata.json", "thumbnail.png", "recording/events.csv", "recording/events.json") or bool(re.fullmatch(r"preview_frames/frame_\d{2,4}\.png", name))


def _safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError(f"Unsafe archive path: {name}")
    return name


def export_project(destination, session, project_dir=None, *, include_recording=True, cancel=None, progress=None):
    """Snapshot the current session; never modify the project or source data."""
    validate_settings(session)
    destination = Path(destination)
    if destination.suffix.lower() != EXTENSION:
        raise ValueError(f"Project bundles must end in {EXTENSION}.")
    snapshot = deepcopy(session)
    source = Path(snapshot.get("source", {}).get("csv_path", ""))
    if not source.is_absolute() and project_dir is not None:
        source = Path(project_dir) / source
    if not source.is_file():
        raise ValueError("Locate the loaded CSV recording before exporting a bundle.")
    source = source.resolve()
    protected = [source, source.with_suffix(".json")]
    if project_dir:
        protected += [Path(project_dir) / name for name in ("session.json", "metadata.json", "thumbnail.png")]
    if destination.resolve() in [path.resolve() for path in protected]:
        raise ValueError("A bundle cannot overwrite project data or the source recording.")
    source_metadata = snapshot["source"].setdefault("metadata", {})
    if source_metadata.get('complete') is False:
        raise ValueError("Load the full recording before exporting a project bundle.")
    expected = source_metadata.get("sha256")
    if not expected:
        expected = _source_hash(source, cancel, progress)
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Source recording checksum is invalid.")
    snapshot["source"]["csv_path"] = "recording/events.csv"
    source_metadata["csv_path"] = "recording/events.csv"
    source_metadata["sha256"] = expected
    snapshot.setdefault("view", {})["is_playing"] = False
    now = now_iso()
    metadata = {"project_name": snapshot.get("project_name", "Imported project"),
                "created_at": now, "last_saved_at": now, "source_csv_path": "recording/events.csv",
                "recording_name": source.name, "thumbnail": "", "preview_frames": []}
    files = {"session.json": _json_bytes(snapshot)}
    if include_recording:
        files["recording/events.csv"] = source
        if source.with_suffix(".json").is_file():
            files["recording/events.json"] = source.with_suffix(".json")
    if project_dir:
        root = Path(project_dir).resolve()
        images = [root / "thumbnail.png"] + sorted((root / "preview_frames").glob("frame_*.png"))
        for path in images:
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if not _allowed(relative):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Project previews must be files inside the project folder.")
            files[relative] = path
            if relative == "thumbnail.png":
                metadata["thumbnail"] = relative
            else:
                metadata["preview_frames"].append(path.name)
    files["metadata.json"] = _json_bytes(metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".bundle-", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    stage = Path(temporary)
    manifest = {"format": "event-studio-project", "version": 1, "recording_included": bool(include_recording),
                "recording_name": source.name, "source_sha256": expected, "files": {}}
    total = sum(value.stat().st_size if isinstance(value, Path) else len(value) for value in files.values())
    done = 0
    try:
        with zipfile.ZipFile(stage, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            for name, value in files.items():
                _check_cancel(cancel)
                digest = hashlib.sha256()
                size = 0
                with archive.open(name, "w", force_zip64=True) as output:
                    if isinstance(value, Path):
                        with value.open("rb") as stream:
                            while chunk := stream.read(CHUNK):
                                _check_cancel(cancel)
                                output.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                                done += len(chunk)
                                if progress:
                                    progress(min(99, int(done * 100 / max(1, total))), f"Packing {name}")
                    else:
                        output.write(value)
                        digest.update(value)
                        size = len(value)
                        done += size
                manifest["files"][name] = {"size": size, "sha256": digest.hexdigest()}
            # A recording modified after load must never be bundled with old measurements.
            if include_recording and manifest["files"]["recording/events.csv"]["sha256"] != expected:
                raise ValueError("The source recording changed since it was loaded. Bundle not exported.")
            if not include_recording:
                if _source_hash(source, cancel, progress) != expected:
                    raise ValueError("The source recording changed since it was loaded.")
            archive.writestr("manifest.json", _json_bytes(manifest))
        _check_cancel(cancel)
        with stage.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(stage, destination)
    finally:
        stage.unlink(missing_ok=True)
    return destination


def import_project(bundle, projects_root, *, cancel=None, progress=None, max_bytes=MAX_BYTES):
    """Validate and stream an archive into a new project without overwriting one."""
    root = Path(projects_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root / ".bundle-import.lock"))
    if not lock.tryLock(1000):
        raise ValueError("Another project import is running. Please try again shortly.")
    try:
        with zipfile.ZipFile(bundle) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES:
                raise ValueError("Bundle contains too many files.")
            names = []
            for entry in entries:
                _safe_name(entry.filename)
                if entry.filename != "manifest.json" and not _allowed(entry.filename):
                    raise ValueError(f"Unexpected bundle file: {entry.filename}")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or entry.is_dir() or entry.flag_bits & 1:
                    raise ValueError("Links, directory entries and encrypted files are not supported.")
                names.append(entry.filename)
            if len({name.casefold() for name in names}) != len(names):
                raise ValueError("Bundle contains duplicate file names.")
            if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > MAX_JSON:
                raise ValueError("Missing or oversized project manifest.")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != "event-studio-project" or manifest.get("version") != 1:
                raise ValueError("Unsupported project bundle format.")
            descriptions = manifest.get("files")
            if not isinstance(descriptions, dict) or set(descriptions) != set(names) - {"manifest.json"}:
                raise ValueError("Bundle contents do not match its manifest.")
            if not {"session.json", "metadata.json"}.issubset(descriptions):
                raise ValueError("Bundle is missing its session or metadata.")
            included = manifest.get("recording_included")
            if not isinstance(included, bool) or included != ("recording/events.csv" in descriptions):
                raise ValueError("Bundle recording declaration is inconsistent.")
            total = sum(entry.file_size for entry in entries)
            if total > max_bytes or total > shutil.disk_usage(root).free:
                raise ValueError("The bundle exceeds the import size limit or available disk space.")
            for name, description in descriptions.items():
                if (not isinstance(description, dict) or description.get("size") != archive.getinfo(name).file_size
                        or not re.fullmatch(r"[0-9a-f]{64}", str(description.get("sha256", "")))):
                    raise ValueError("Invalid file size or checksum in the bundle manifest.")
                if name.endswith(".json") and description["size"] > MAX_JSON:
                    raise ValueError("Bundle JSON file is too large.")
            with tempfile.TemporaryDirectory(prefix=".bundle-import-", dir=root) as temporary:
                staging = Path(temporary).resolve()
                if staging.parent != root:
                    raise ValueError("Import staging directory escaped the projects folder.")
                done = 0
                for name, description in descriptions.items():
                    _check_cancel(cancel)
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open(name) as source, target.open("xb") as output:
                        while chunk := source.read(CHUNK):
                            _check_cancel(cancel)
                            size += len(chunk)
                            if size > description["size"]:
                                raise ValueError("Archive data exceeds its declared size.")
                            output.write(chunk)
                            digest.update(chunk)
                            done += len(chunk)
                            if progress:
                                progress(min(99, int(done * 100 / max(1, total))), f"Importing {name}")
                    if size != description["size"] or digest.hexdigest() != description["sha256"]:
                        raise ValueError(f"Bundle checksum mismatch: {name}")
                session = json.loads((staging / "session.json").read_text(encoding="utf-8"))
                validate_settings(session)
                if session.get("source", {}).get("csv_path") != "recording/events.csv":
                    raise ValueError("Bundle session must reference its relative recording path.")
                expected = session.get("source", {}).get("metadata", {}).get("sha256")
                if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
                        or expected != manifest.get("source_sha256")):
                    raise ValueError("Bundle source identity is inconsistent.")
                if included and descriptions["recording/events.csv"]["sha256"] != expected:
                    raise ValueError("Bundled recording does not match the saved analysis.")
                resolve_session_source(session, staging)
                metadata = json.loads((staging / "metadata.json").read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    raise ValueError("Project metadata must be an object.")
                name = sanitize_project_name(str(session.get("project_name", "Imported project"))).rstrip(". ")
                if not name or Path(name).is_reserved() or name in (".", "..") or name.startswith("."):
                    name = "Imported project"
                destination = unique_project_dir(root, name)
                metadata.update(project_name=destination.name, source_csv_path="recording/events.csv",
                                recording_name=str(manifest.get("recording_name", "events.csv")),
                                created_at=now_iso(), last_saved_at=now_iso())
                session["project_name"] = destination.name
                save_json(staging / "session.json", session)
                save_json(staging / "metadata.json", metadata)
                _check_cancel(cancel)
                staging.rename(destination)
                return destination
    finally:
        lock.unlock()
