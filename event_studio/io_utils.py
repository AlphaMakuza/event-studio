"""Staged measurement exports with rollback of an existing CSV/JSON pair."""

from pathlib import Path
import csv
import os
import shutil
import tempfile


def commit_pair(data, metadata, destination, sidecar):
    targets = [Path(destination), Path(sidecar)]
    with tempfile.TemporaryDirectory(
        prefix="rollback-", dir=targets[0].parent
    ) as directory:
        backups = []
        for i, target in enumerate(targets):
            backup = Path(directory) / str(i)
            if target.exists():
                shutil.copy2(target, backup)
                backups.append(backup)
            else:
                backups.append(None)
        committed = 0
        try:
            for source, target in zip((data, metadata), targets):
                os.replace(source, target)
                committed += 1
        except Exception:
            for target, backup in zip(targets[:committed], backups[:committed]):
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    shutil.copy2(backup, target)
            raise


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
