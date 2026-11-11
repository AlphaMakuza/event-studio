"""Use the separately installed MSVC runtime instead of NumPy's private copy.

NumPy wheels rename an MSVC DLL and its import strings. When that DLL is not
redistributed, the matching imports must refer to the standard installed name.
Only import-name storage is changed, without relocating executable code.
"""
import hashlib
from pathlib import Path
import re

import pefile


def retarget_private_msvc(folder):
    modifications = []
    for file in sorted(Path(folder).rglob("*")):
        if file.suffix.lower() not in (".dll", ".pyd"):
            continue
        original = file.read_bytes()
        binary = pefile.PE(data=original, fast_load=True)
        binary.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        edits = []
        changed = bytearray(original)
        for entry in getattr(binary, "DIRECTORY_ENTRY_IMPORT", []):
            if re.fullmatch(rb"msvcp[0-9]+-[0-9a-f]+\.dll", entry.dll, re.IGNORECASE):
                standard = entry.dll.split(b"-", 1)[0] + b".dll"
                offset = binary.get_offset_from_rva(entry.struct.Name)
                assert original[offset:offset + len(entry.dll)] == entry.dll
                changed[offset:offset + len(entry.dll)] = standard.ljust(len(entry.dll), b"\0")
                edits.append({"from": entry.dll.decode(), "to": standard.decode()})
        binary.close()
        if edits:
            file.write_bytes(changed)
            # Ensure the resulting import directory parses and names are correct.
            checked = pefile.PE(str(file), fast_load=True)
            checked.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            assert not any(re.fullmatch(rb"msvcp[0-9]+-[0-9a-f]+\.dll", e.dll, re.IGNORECASE)
                           for e in getattr(checked, "DIRECTORY_ENTRY_IMPORT", []))
            checked.close()
            modifications.append({"path": str(file.relative_to(folder)), "original_sha256": hashlib.sha256(original).hexdigest(),
                                  "modified_sha256": hashlib.sha256(changed).hexdigest(), "imports": edits})
    return modifications
