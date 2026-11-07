from __future__ import annotations

import os
import subprocess
import shlex
from uuid import uuid4
from pathlib import Path
from typing import Optional, Tuple

# If you have multiple WSL distros, set it, else leave None
WSL_DISTRO: Optional[str] = None

# Where we stage imports inside WSL (Linux path)
WSL_IMPORT_DIR = "$HOME/__event_studio_imports__"


def _shell_path(path: str) -> str:
    # Expand only our trusted HOME prefix; filenames stay literal shell arguments.
    if path.startswith("$HOME/"):
        return '"$HOME"/' + shlex.quote(path[len("$HOME/"):])
    return shlex.quote(path)

# Candidate OpenEB bin folders (we'll probe these first)
OPENEB_BIN_CANDIDATES = [
    "$HOME/openeb/build/bin",
    "$HOME/openeb/build/Release/bin",
    "$HOME/openeb/build-release/bin",
    "$HOME/openeb/build-relwithdebinfo/bin",
]


# -----------------------------
# WSL helpers
# -----------------------------

def _wsl_base_cmd() -> list[str]:
    cmd = ["wsl.exe"]
    if WSL_DISTRO:
        cmd += ["-d", WSL_DISTRO]
    return cmd


def _run_wsl(cmd: str) -> subprocess.CompletedProcess[str]:
    """
    Run a command inside WSL bash -lc.
    Raises RuntimeError with stdout/stderr if it fails.
    """
    p = subprocess.run(
        _wsl_base_cmd() + ["bash", "-lc", cmd],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"WSL command failed ({p.returncode}).\n"
            f"CMD: {cmd}\n"
            f"STDOUT:\n{p.stdout}\n"
            f"STDERR:\n{p.stderr}"
        )
    return p


def _wslpath(win_path: Path) -> str:
    """
    Convert Windows path -> absolute WSL path using wslpath.
    Handles spaces safely.
    """
    p = subprocess.run(
        _wsl_base_cmd() + ["wslpath", "-a", str(win_path)],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"wslpath failed.\nWIN: {win_path}\nSTDERR:\n{p.stderr}"
        )
    return p.stdout.strip()


def _find_openeb_bin() -> str:
    """
    Find an OpenEB bin directory that contains metavision_file_to_hdf5 and metavision_file_to_csv.
    """
    for b in OPENEB_BIN_CANDIDATES:
        try:
            _run_wsl(f'test -d "{b}"')
            _run_wsl(f'test -x "{b}/metavision_file_to_hdf5"')
            _run_wsl(f'test -x "{b}/metavision_file_to_csv"')
            return b
        except Exception:
            pass

    # Fallback: search under ~/openeb
    p = _run_wsl(
        'find "$HOME/openeb" -path "*bin/metavision_file_to_hdf5" -type f 2>/dev/null | head -n 1'
    )
    found = p.stdout.strip()
    if found:
        return str(Path(found).parent).replace("\\", "/")

    raise RuntimeError(
        "Could not locate OpenEB bin folder containing metavision_file_to_hdf5 and metavision_file_to_csv.\n"
        "Make sure OpenEB is built in WSL and the tools exist under ~/openeb/build/bin."
    )


def _wsl_stage_in_from_windows(win_src: Path, wsl_dst: str) -> None:
    """
    Copy Windows file -> WSL import directory.
    """
    wsl_src = _wslpath(win_src)
    _run_wsl(f'mkdir -p "{WSL_IMPORT_DIR}"')
    _run_wsl(f'cp -- {_shell_path(wsl_src)} {_shell_path(wsl_dst)}')


def _wsl_stage_out_to_windows(wsl_src: str, win_dst: Path) -> None:
    """
    Copy WSL file -> Windows destination.
    IMPORTANT: Create folders on Windows side (Python) to avoid quoting bugs.
    """
    win_dst.parent.mkdir(parents=True, exist_ok=True)
    wsl_dst = _wslpath(win_dst)
    _run_wsl(f'cp -- {_shell_path(wsl_src)} {_shell_path(wsl_dst)}')


# -----------------------------
# Converters
# -----------------------------

def convert_dat_to_h5_windows(
    dat_path: str | os.PathLike,
    out_h5_path: str | os.PathLike | None = None,
    *,
    out_dir: str | os.PathLike | None = None,
) -> Path:
    """
    Convert a Windows .dat file -> Windows .h5 using OpenEB inside WSL.

    You can choose output in two ways:
      - out_h5_path: explicit full output file path
      - out_dir: output folder (filename will be dat.stem + ".h5")

    Returns Windows path to the generated .h5.
    """
    dat_path = Path(dat_path).expanduser().resolve()
    if dat_path.suffix.lower() != ".dat":
        raise ValueError(f"Expected a .dat file, got: {dat_path}")

    if out_h5_path is not None and out_dir is not None:
        raise ValueError("Use either out_h5_path OR out_dir, not both.")

    if out_h5_path is None:
        if out_dir is None:
            out_h5_path = dat_path.with_suffix(".h5")
        else:
            out_dir = Path(out_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            out_h5_path = out_dir / (dat_path.stem + ".h5")

    out_h5_path = Path(out_h5_path).expanduser().resolve()
    if out_h5_path.exists():
        raise FileExistsError(f"Conversion output already exists: {out_h5_path}")

    openeb_bin = _find_openeb_bin()
    tool_hdf5 = f"{openeb_bin}/metavision_file_to_hdf5"

    token = uuid4().hex
    wsl_dat = f'{WSL_IMPORT_DIR}/{token}_{dat_path.name}'
    wsl_h5 = f'{WSL_IMPORT_DIR}/{token}_{out_h5_path.name}'

    # stage in
    _wsl_stage_in_from_windows(dat_path, wsl_dat)

    # convert
    _run_wsl(f'{_shell_path(tool_hdf5)} -i {_shell_path(wsl_dat)} -o {_shell_path(wsl_h5)}')

    # stage out
    _wsl_stage_out_to_windows(wsl_h5, out_h5_path)
    _run_wsl(f'rm -f -- {_shell_path(wsl_dat)} {_shell_path(wsl_h5)}')

    return out_h5_path


def h5_to_csv_windows(
    h5_path: str | os.PathLike,
    out_csv_path: str | os.PathLike,
) -> Path:
    """
    Convert a Windows .h5 -> Windows .csv using OpenEB inside WSL.
    Returns Windows path to the generated CSV.
    """
    h5_path = Path(h5_path).expanduser().resolve()
    out_csv_path = Path(out_csv_path).expanduser().resolve()
    if out_csv_path.exists():
        raise FileExistsError(f"Conversion output already exists: {out_csv_path}")

    if not h5_path.exists():
        raise FileNotFoundError(f"H5 does not exist: {h5_path}")

    openeb_bin = _find_openeb_bin()
    tool_csv = f"{openeb_bin}/metavision_file_to_csv"

    token = uuid4().hex
    wsl_h5 = f'{WSL_IMPORT_DIR}/{token}_{h5_path.name}'
    wsl_csv = f'{WSL_IMPORT_DIR}/{token}_{out_csv_path.name}'

    # stage in
    _wsl_stage_in_from_windows(h5_path, wsl_h5)

    # convert (no -v; yours doesn't support it)
    _run_wsl(f'{_shell_path(tool_csv)} -i {_shell_path(wsl_h5)} -o {_shell_path(wsl_csv)}')

    # stage out
    _wsl_stage_out_to_windows(wsl_csv, out_csv_path)
    _run_wsl(f'rm -f -- {_shell_path(wsl_h5)} {_shell_path(wsl_csv)}')

    return out_csv_path


def convert_dat_to_h5_and_csv_windows(
    dat_path: str | os.PathLike,
    project_root: str | os.PathLike,
) -> Tuple[Path, Path]:
    """
    Convenience: .dat -> .h5 and then .h5 -> .csv.
    Output goes to: <project_root>/data/converted/
    """
    project_root = Path(project_root).expanduser().resolve()
    out_dir = project_root / "data" / "converted"
    out_dir.mkdir(parents=True, exist_ok=True)

    dat_path = Path(dat_path).expanduser().resolve()
    stem = dat_path.stem  # includes _td, etc.

    out_h5 = out_dir / f"{stem}.h5"
    out_csv = out_dir / f"{stem}.csv"

    h5_path = convert_dat_to_h5_windows(dat_path, out_h5)
    csv_path = h5_to_csv_windows(h5_path, out_csv)

    return h5_path, csv_path
