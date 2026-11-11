"""Keep source license notices readable without deeply nested extraction paths."""
import hashlib
import json
from pathlib import Path
import shutil


def shorten_dependencies(folder):
    folder = Path(folder).resolve(strict=True)
    root = folder / "_internal" / "release-docs" / "third-party"
    inventory_path = root / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    target = root / "texts"
    target.mkdir(exist_ok=True)
    mapping = {}
    originals = [p for p in sorted(root.rglob("*")) if p.is_file()
                 and p.parent != root and not p.is_relative_to(target)]
    for number, original in enumerate(originals, 1):
        name = f"texts/{number:04d}{original.suffix[:8]}"
        destination = root / name
        shutil.copy2(original, destination)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest
        mapping[original.relative_to(root).as_posix()] = {"file": name, "sha256": digest}
    if not mapping:
        return
    for item in inventory:
        item["license_files"] = [mapping.get(name.replace("\\", "/"), {}).get("file", name)
                                 for name in item["license_files"]]
    inventory_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (root / "SOURCE-PATHS.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    for directory in root.iterdir():
        if directory.is_dir() and directory != target:
            assert directory.resolve().is_relative_to(folder)
            shutil.rmtree(directory)


def shorten_notices(folder):
    folder = Path(folder).resolve(strict=True)
    legal = folder / "_internal" / "release-docs" / "legal"
    source = legal / "qt-source-notices"
    if not source.exists():
        return
    assert source.resolve().is_relative_to(folder), "Notice directory escaped application folder"
    target = legal / "qt-notices"
    target.mkdir(exist_ok=True)
    inventory = []
    for number, original in enumerate(sorted(source.rglob("*")), 1):
        if not original.is_file():
            continue
        name = f"{number:04d}{original.suffix[:8]}"
        destination = target / name
        shutil.copy2(original, destination)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest
        inventory.append({"original_path": original.relative_to(source).as_posix(),
                          "file": name, "sha256": digest})
    (target / "INDEX.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (target / "README.txt").write_text(
        "Original Qt/PySide license and attribution files, unchanged.\n"
        "INDEX.json maps short filenames to their source paths and SHA-256 hashes.\n"
        "Short filenames avoid Windows ZIP extraction path limits.\n", encoding="utf-8")
    shutil.rmtree(source)
