"""Independent, atomic recovery snapshots; manual sessions remain authoritative."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from contextlib import contextmanager
from PySide6.QtCore import QLockFile

from .project_utils import load_json, now_iso, save_json, session_json_path
from .session_validation import validate_settings

AUTOSAVE = ".autosave.json"
PREVIOUS = ".autosave.previous.json"
_UNCHECKED = object()


def recovery_revision(directory):
    path = Path(directory) / AUTOSAVE
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@contextmanager
def _recovery_lock(directory, expected_revision):
    lock = QLockFile(str(Path(directory) / ".autosave.lock"))
    if not lock.tryLock(1000):
        raise ValueError("Another recovery operation is running. Please try again.")
    try:
        if expected_revision is not _UNCHECKED and expected_revision != recovery_revision(directory):
            raise ValueError("Recovery was changed by another window. Its snapshot has been kept; save your work to a separate project bundle.")
        yield
    finally:
        lock.unlock()


def session_for_storage(session, directory):
    result = deepcopy(session)
    source = result.get("source", {})
    value = source.get("csv_path", "")
    if value:
        path = Path(value)
        if path.is_absolute() and path.resolve().is_relative_to(Path(directory).resolve()):
            source["csv_path"] = path.resolve().relative_to(Path(directory).resolve()).as_posix()
        if isinstance(source.get("metadata"), dict):
            source["metadata"]["csv_path"] = source["csv_path"]
    return result


def resolve_session_source(session, directory):
    result = deepcopy(session)
    source = result.get("source", {})
    if not isinstance(source, dict) or not isinstance(source.get("csv_path", ""), str):
        raise ValueError("Session source must contain a recording path.")
    value = source.get("csv_path", "")
    if value:
        path = Path(value)
        if not path.is_absolute():
            root = Path(directory).resolve()
            path = (root / path).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Relative recording path escapes the project folder.")
        source["csv_path"] = str(path)
        if isinstance(source.get("metadata"), dict):
            source["metadata"]["csv_path"] = str(path)
    return result


def session_digest(session, directory):
    result = session_for_storage(session, directory)
    result.pop("saved_at", None)
    result.get("view", {}).pop("is_playing", None)
    data = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def recovery_available(directory):
    return any((Path(directory) / name).is_file() for name in (AUTOSAVE, PREVIOUS))


def write_recovery(directory, session, *, expected_revision=_UNCHECKED):
    directory = Path(directory)
    snapshot = session_for_storage(session, directory)
    validate_settings(snapshot)
    snapshot.setdefault("view", {})["is_playing"] = False
    record = {"recovery_format": 1, "saved_at": now_iso(), "session": snapshot}
    with _recovery_lock(directory, expected_revision):
        previous = load_json(directory / AUTOSAVE)
        if isinstance(previous, dict) and previous.get("recovery_format") == 1:
            try:
                validate_settings(previous.get("session"))
            except (ValueError, TypeError, AttributeError):
                pass
            else:
                save_json(directory / PREVIOUS, previous)
        save_json(directory / AUTOSAVE, record)
        return recovery_revision(directory)


def read_recovery(directory):
    """Fall back to the last valid snapshot if the newest is damaged."""
    directory = Path(directory)
    failures = []
    saved = load_json(session_json_path(directory))
    for name in (AUTOSAVE, PREVIOUS):
        path = directory / name
        if not path.exists():
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("recovery_format") != 1:
                raise ValueError("Unknown recovery format")
            validate_settings(record.get("session"))
            if saved and session_digest(saved, directory) == session_digest(record["session"], directory):
                return None
            return {**record, "path": path}
        except (ValueError, TypeError, AttributeError, OSError) as exc:
            failures.append(f"{name}: {exc}")
    if failures:
        raise ValueError("Recovery snapshots could not be read. They have been kept.\n" + "\n".join(failures))
    return None


def clear_recovery(directory, *, expected_revision=_UNCHECKED):
    with _recovery_lock(directory, expected_revision):
        for name in (AUTOSAVE, PREVIOUS):
            (Path(directory) / name).unlink(missing_ok=True)
