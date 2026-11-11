from __future__ import annotations

import json
import re
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtGui import QImage


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sanitize_project_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name or "Untitled Project"


def ensure_projects_root(projects_root: Path) -> Path:
    projects_root.mkdir(parents=True, exist_ok=True)
    return projects_root


def unique_project_dir(projects_root: Path, project_name: str) -> Path:
    base = sanitize_project_name(project_name)
    candidate = projects_root / base
    if not candidate.exists():
        return candidate

    i = 2
    while True:
        candidate = projects_root / f"{base} ({i})"
        if not candidate.exists():
            return candidate
        i += 1


def create_project_dir(projects_root: Path, project_name: str) -> Path:
    projects_root = ensure_projects_root(projects_root)
    project_dir = unique_project_dir(projects_root, project_name)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def session_json_path(project_dir: Path) -> Path:
    return project_dir / "session.json"


def metadata_json_path(project_dir: Path) -> Path:
    return project_dir / "metadata.json"


def thumbnail_path(project_dir: Path) -> Path:
    return project_dir / "thumbnail.png"


def preview_dir(project_dir: Path) -> Path:
    return project_dir / "preview_frames"


def _save_gray_png(frame: np.ndarray, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    arr = np.ascontiguousarray(frame, dtype=np.uint8)
    if arr.ndim == 2:
        fmt = QImage.Format_Grayscale8
    elif arr.ndim == 3 and arr.shape[2] == 3:
        fmt = QImage.Format_RGB888
    else:
        raise ValueError("Expected an HxW grayscale or HxWx3 RGB frame.")
    h, w = arr.shape[:2]
    qimg = QImage(arr.data, w, h, arr.strides[0], fmt).copy()
    if not qimg.save(str(out_path)):
        raise RuntimeError(f"Failed to save image: {out_path}")


def save_preview_frames(project_dir: Path, frames: list[np.ndarray]) -> list[str]:
    pdir = preview_dir(project_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    saved = []
    with tempfile.TemporaryDirectory(prefix="previews-", dir=project_dir) as temporary:
        staging = Path(temporary)
        for i, frame in enumerate(frames):
            out = staging / f"frame_{i:02d}.png"
            _save_gray_png(frame, out)
            saved.append(out.name)
        for name in saved:
            os.replace(staging / name, pdir / name)
    for old in pdir.glob("*.png"):
        if old.name not in saved:
            old.unlink()
    return saved


def save_recording_preview(project_dir: Path, frames: list[np.ndarray]) -> None:
    """Replace browser artwork while leaving saved analysis and source untouched."""
    if not frames:
        return
    files = save_preview_frames(project_dir, frames)
    _save_gray_png(frames[0], thumbnail_path(project_dir))
    meta = load_json(metadata_json_path(project_dir), default={}) or {}
    meta.update(thumbnail="thumbnail.png", preview_frames=files)
    save_json(metadata_json_path(project_dir), meta)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_project_bundle(
    project_dir: Path,
    project_name: str,
    session_data: dict,
    thumbnail_frame: np.ndarray | None,
    preview_frames: list[np.ndarray],
) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)

    if thumbnail_frame is not None:
        _save_gray_png(thumbnail_frame, thumbnail_path(project_dir))

    preview_files = save_preview_frames(project_dir, preview_frames) if preview_frames else []

    # Commit analysis state only after image generation succeeds.
    save_json(session_json_path(project_dir), session_data)

    meta_old = load_json(metadata_json_path(project_dir), default={}) or {}
    meta = {
        "project_name": project_name,
        "created_at": meta_old.get("created_at", now_iso()),
        "last_opened_at": meta_old.get("last_opened_at", now_iso()),
        "last_saved_at": now_iso(),
        "source_csv_path": session_data.get("source", {}).get("csv_path", ""),
        "thumbnail": "thumbnail.png" if thumbnail_frame is not None else "",
        "preview_frames": preview_files,
    }
    save_json(metadata_json_path(project_dir), meta)


def touch_project_opened(project_dir: Path) -> None:
    meta = load_json(metadata_json_path(project_dir), default={}) or {}
    if not meta:
        meta = {"project_name": project_dir.name, "created_at": now_iso()}
    meta["last_opened_at"] = now_iso()
    save_json(metadata_json_path(project_dir), meta)


def rename_project(project_dir: Path, new_name: str) -> None:
    meta = load_json(metadata_json_path(project_dir), default={}) or {}
    meta["project_name"] = sanitize_project_name(new_name)
    save_json(metadata_json_path(project_dir), meta)


def rename_project_folder(projects_root: Path, project_dir: Path, new_name: str) -> Path:
    """Rename a project and rebase references to files stored inside its folder."""
    original = Path(project_dir)
    source = original.resolve(strict=True)
    root = Path(projects_root).resolve(strict=True)
    if (source.parent != root or original.is_symlink() or original.is_junction()
            or not source.is_dir()):
        raise ValueError("The project must be a folder directly inside the projects directory.")
    name = sanitize_project_name(new_name).rstrip(". ")
    if not name or name in (".", "..") or Path(name).is_reserved():
        raise ValueError("Please choose a valid project folder name.")
    destination = root / name
    if destination.exists() and destination.resolve() != source:
        raise ValueError("A project with that folder name already exists.")

    def rebase(value):
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebase(item) for item in value]
        if isinstance(value, str):
            path = Path(value)
            if path.is_absolute():
                path = path.resolve()
                if path.is_relative_to(source):
                    return str(destination / path.relative_to(source))
        return value

    updates = []
    for filename in ("metadata.json", "session.json", ".autosave.json", ".autosave.previous.json"):
        path = source / filename
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                old = json.load(stream)
            updated = rebase(old)
            updated["project_name"] = name
            if filename.startswith(".autosave") and isinstance(updated.get("session"), dict):
                updated["session"]["project_name"] = name
            updates.append((filename, old, updated))
        elif filename == "metadata.json":
            updates.append((filename, None, {"project_name": name}))
    source.rename(destination)
    try:
        for filename, _, updated in updates:
            save_json(destination / filename, updated)
    except Exception:
        for filename, old, _ in updates:
            if old is None:
                (destination / filename).unlink(missing_ok=True)
            else:
                save_json(destination / filename, old)
        destination.rename(source)
        raise
    return destination


def list_projects(projects_root: Path) -> list[dict]:
    ensure_projects_root(projects_root)

    projects: list[dict] = []
    for child in projects_root.iterdir():
        if child.name.startswith(".") or not child.is_dir() or child.is_symlink() or child.is_junction():
            continue

        meta = load_json(metadata_json_path(child), default={}) or {}
        sess_exists = session_json_path(child).exists()
        from .recovery import recovery_available
        has_recovery = recovery_available(child)
        thumb = thumbnail_path(child)
        pdir = preview_dir(child)

        preview_files = []
        if pdir.exists():
            preview_files = sorted(str(p) for p in pdir.glob("*.png"))

        last_saved = meta.get("last_saved_at")
        if not last_saved:
            try:
                last_saved = datetime.fromtimestamp(child.stat().st_mtime).isoformat(timespec="seconds")
            except Exception:
                last_saved = ""

        projects.append(
            {
                "project_dir": str(child),
                "project_name": meta.get("project_name", child.name),
                "created_at": meta.get("created_at", ""),
                "last_opened_at": meta.get("last_opened_at", ""),
                "last_saved_at": last_saved,
                "source_csv_path": meta.get("source_csv_path", ""),
                "thumbnail_path": str(thumb) if thumb.exists() else "",
                "preview_frames": preview_files,
                "has_session": sess_exists,
                "has_recovery": has_recovery,
            }
        )

    projects.sort(key=lambda x: x.get("last_saved_at", ""), reverse=True)
    return projects
