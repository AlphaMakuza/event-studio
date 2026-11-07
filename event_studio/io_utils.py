"""Staged measurement exports with rollback of an existing CSV/JSON pair."""

from pathlib import Path
import csv
import os
import shutil
import tempfile


class CommitRecoveryError(RuntimeError):
    """Output rollback failed; recovery copies remain at recovery_directory."""

    def __init__(self, message, recovery_directory):
        super().__init__(message)
        self.recovery_directory = Path(recovery_directory)


def commit_pair(data, metadata, destination, sidecar):
    targets = [Path(destination), Path(sidecar)]
    parent = targets[0].parent.resolve()
    directory = Path(tempfile.mkdtemp(prefix="rollback-", dir=parent)).resolve()
    retain_recovery = False
    try:
        backups = []
        for i, target in enumerate(targets):
            backup = directory / f"{i}.previous"
            if target.exists():
                shutil.copyfile(target, backup)
                backups.append(backup)
            else:
                backups.append(None)
        committed = 0
        try:
            for source, target in zip((data, metadata), targets):
                os.replace(source, target)
                committed += 1
        except Exception as original:
            failures = []
            for target, backup in zip(targets[:committed], backups[:committed]):
                try:
                    if backup is None:
                        target.unlink(missing_ok=True)
                    else:
                        shutil.copyfile(backup, target)
                except Exception as exc:
                    failures.append(
                        {"target": str(target.resolve()), "error": str(exc)}
                    )
            if failures:
                retain_recovery = True
                import json

                journal = {
                    "original_error": str(original),
                    "rollback_failures": failures,
                    "backups": [
                        {
                            "target": str(target.resolve()),
                            "backup": str(backup) if backup else None,
                        }
                        for target, backup in zip(targets, backups)
                    ],
                }
                try:
                    (directory / "recovery.json").write_text(
                        json.dumps(journal, indent=2), encoding="utf-8"
                    )
                except OSError:
                    pass  # Keep the actual previous files even if journaling fails.
                raise CommitRecoveryError(
                    f"Export failed and the previous output could not be fully restored. Recovery copies were retained at {directory}",
                    directory,
                ) from original
            raise
    finally:
        if not retain_recovery:
            # Delete only the exact temporary directory created under this
            # explicitly selected output parent, never an unchecked path.
            if directory.parent != parent or not directory.name.startswith("rollback-"):
                raise RuntimeError(
                    "Recovery cleanup path escaped its output directory."
                )
            shutil.rmtree(directory)


def export_table(path, columns, rows, metadata):
    from .science import fingerprint
    from .project_utils import save_json
    from .version import __version__, ANALYSIS_VERSION

    path = Path(path)
    if path.suffix.lower() != ".csv":
        raise ValueError("Measurement exports must use a .csv filename.")
    source_path = metadata.get("source", {}).get("csv_path")
    if source_path and path.resolve() == Path(source_path).resolve():
        raise ValueError("Measurements cannot overwrite the source recording.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="measurement-", dir=path.parent
    ) as directory:
        stage = Path(directory) / path.name
        with stage.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
        info = {
            **metadata,
            "classification": "DERIVED",
            "software_version": __version__,
            "algorithm_version": ANALYSIS_VERSION,
            "csv_sha256": fingerprint(stage),
        }
        save_json(stage.with_suffix(".json"), info)
        commit_pair(stage, stage.with_suffix(".json"), path, path.with_suffix(".json"))
