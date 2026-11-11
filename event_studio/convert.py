from __future__ import annotations

import os
import base64
import subprocess
import shlex
import time
from uuid import uuid4
from pathlib import Path, PurePosixPath
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


def _decode_wsl_output(value) -> str:
    """Linux output is UTF-8; wsl.exe startup failures may be UTF-16LE."""
    if isinstance(value, str):
        return value
    if not value:
        return ""
    if value.startswith((b'\xff\xfe', b'\xfe\xff')):
        return value.decode('utf-16', errors='replace')
    if b'\x00' in value:
        return value.decode('utf-16-le', errors='replace').lstrip('\ufeff')
    return value.decode('utf-8', errors='replace')


def _run_wsl(cmd: str, *, cancel=None, progress=None) -> subprocess.CompletedProcess[str]:
    """
    Run a command inside WSL bash -lc.
    Raises RuntimeError with stdout/stderr if it fails.
    """
    if cancel is None and progress is None:
        p = subprocess.run(_wsl_base_cmd() + ["bash", "-lc", cmd], capture_output=True)
    else:
        from .filters import CancelledError
        if cancel and cancel():
            raise CancelledError("Recording import cancelled.")
        # The PID belongs to this one converter; cancelling must not stop other
        # WSL jobs or shut down the user's distribution.
        pidfile = f"/tmp/ebs-converter-{uuid4().hex}.pid"
        wrapped = f"echo $$ > {shlex.quote(pidfile)}; exec {cmd}"
        process = subprocess.Popen(_wsl_base_cmd() + ["bash", "-lc", wrapped],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        started = time.monotonic()
        try:
            while True:
                if cancel and cancel():
                    _run_wsl(f'if test -f {shlex.quote(pidfile)}; then kill -TERM "$(cat {shlex.quote(pidfile)})" 2>/dev/null || true; fi')
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise CancelledError("Recording import cancelled.")
                try:
                    stdout, stderr = process.communicate(timeout=0.25)
                    p = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
                    break
                except subprocess.TimeoutExpired:
                    if progress:
                        progress(0, f"Converting HDF5 to CSV: {int(time.monotonic() - started)} s elapsed. Large recordings can take several minutes.")
        finally:
            _run_wsl(f"rm -f -- {shlex.quote(pidfile)}")
    p.stdout, p.stderr = _decode_wsl_output(p.stdout), _decode_wsl_output(p.stderr)
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
    )
    p.stdout, p.stderr = _decode_wsl_output(p.stdout), _decode_wsl_output(p.stderr)
    if p.returncode != 0:
        raise RuntimeError(
            f"wslpath failed.\nWIN: {win_path}\nSTDERR:\n{p.stderr}"
        )
    return p.stdout.strip()


def _find_openeb_bin() -> str:
    """
    Find an OpenEB bin directory that contains metavision_file_to_hdf5 and metavision_file_to_csv.
    """
    try:
        _run_wsl('printf EBS_WSL_READY')
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            "DAT and HDF5 conversion needs Windows Subsystem for Linux (WSL), a Linux distribution, "
            "and the OpenEB conversion tools on this computer. They are not included in the app ZIP.\n\n"
            "WSL could not start. Open a Windows terminal and run 'wsl --status' and 'wsl --list --verbose' "
            "to check its setup. CSV recordings open directly without WSL or OpenEB.\n\n"
            f"Setup details:\n{exc}"
        ) from exc
    for b in OPENEB_BIN_CANDIDATES:
        try:
            _run_wsl(f'test -d "{b}"')
            _run_wsl(f'test -x "{b}/metavision_file_to_hdf5"')
            _run_wsl(f'test -x "{b}/metavision_file_to_csv"')
            return b
        except RuntimeError:
            pass

    # Fallback: search under ~/openeb
    p = _run_wsl('command -v metavision_file_to_hdf5 || true')
    found = p.stdout.strip()
    if found:
        directory = str(PurePosixPath(found).parent)
        try:
            _run_wsl(f'test -x {_shell_path(directory + "/metavision_file_to_csv")}')
            return directory
        except RuntimeError:
            pass
    p = _run_wsl(
        '(find "$HOME/openeb" -path "*bin/metavision_file_to_hdf5" -type f 2>/dev/null || true) | head -n 1'
    )
    found = p.stdout.strip()
    if found:
        directory = str(PurePosixPath(found).parent)
        try:
            _run_wsl(f'test -x {_shell_path(directory + "/metavision_file_to_hdf5")} && '
                     f'test -x {_shell_path(directory + "/metavision_file_to_csv")}')
            return directory
        except RuntimeError:
            pass

    raise RuntimeError(
        "WSL starts, but the OpenEB recording converters were not found on this computer.\n"
        "DAT/HDF5 conversion requires metavision_file_to_hdf5 and metavision_file_to_csv, installed separately "
        "inside WSL. Build OpenEB under ~/openeb or put both converters on the Linux PATH.\n\n"
        "You can open a CSV recording directly without these tools."
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
    if not dat_path.is_file():
        raise FileNotFoundError(f"DAT does not exist: {dat_path}")

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
    # Boost's filesystem-path option parser in some OpenEB builds rejects
    # whitespace even when the shell passes a correctly quoted argument.
    # Keep user filenames on Windows; converter arguments use ASCII tokens.
    wsl_dat = f'{WSL_IMPORT_DIR}/{token}.dat'
    wsl_h5 = f'{WSL_IMPORT_DIR}/{token}.h5'

    # stage in
    try:
        _wsl_stage_in_from_windows(dat_path, wsl_dat)
        _run_wsl(f'{_shell_path(tool_hdf5)} -i {_shell_path(wsl_dat)} -o {_shell_path(wsl_h5)}')
        _wsl_stage_out_to_windows(wsl_h5, out_h5_path)
    finally:
        _run_wsl(f'rm -f -- {_shell_path(wsl_dat)} {_shell_path(wsl_h5)}')

    return out_h5_path


def h5_to_csv_windows(
    h5_path: str | os.PathLike,
    out_csv_path: str | os.PathLike,
    *, cancel=None, progress=None, max_events=None,
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
    wsl_h5 = f'{WSL_IMPORT_DIR}/{token}.h5'
    wsl_csv = f'{WSL_IMPORT_DIR}/{token}.csv'

    if progress:
        progress(0, "Copying HDF5 recording to the converter...")
    try:
        _wsl_stage_in_from_windows(h5_path, wsl_h5)
        if max_events is None:
            command = f'{_shell_path(tool_csv)} -i {_shell_path(wsl_h5)} -o {_shell_path(wsl_csv)}'
        else:
            if not isinstance(max_events, int) or max_events < 1:
                raise ValueError("Preview event limit must be a positive integer.")
            # This OpenEB version has no event-limit flag. A bounded FIFO reader
            # keeps an exact CSV prefix and stops the writer with SIGPIPE.
            # Two extra lines allow the loader to detect truncation, with or
            # without a CSV header. No event values or timestamps are invented.
            fifo = wsl_csv + ".fifo"
            cleanup = ('test -z "$writer" || kill "$writer" 2>/dev/null || true; '
                       'test -z "$reader" || kill "$reader" 2>/dev/null || true; '
                       f'rm -f -- {_shell_path(fifo)}')
            script = (
                'writer=; reader=; '
                'trap ' + shlex.quote(cleanup) + ' EXIT; '
                "trap 'exit 130' TERM INT; "
                f'mkfifo -- {_shell_path(fifo)} || exit $?; '
                f'head -n {max_events + 2} {_shell_path(fifo)} > {_shell_path(wsl_csv)} & reader=$!; '
                f'{_shell_path(tool_csv)} -i {_shell_path(wsl_h5)} -o {_shell_path(fifo)} & writer=$!; '
                'wait "$writer"; code=$?; writer=; '
                # If opening the input failed before opening the FIFO, head
                # would wait forever; stop it and preserve the converter error.
                'if test "$code" != 0 && test "$code" != 141; then exit "$code"; fi; '
                'wait "$reader"; read_code=$?; reader=; exit "$read_code"'
            )
            # Transfer script text as data; Windows/WSL command-line quoting
            # must not expand the script's job IDs or shell variables early.
            script_path = wsl_csv + ".sh"
            encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
            _run_wsl(f'printf %s {encoded} | base64 -d > {_shell_path(script_path)}')
            command = 'bash ' + _shell_path(script_path)
        try:
            _run_wsl(command, cancel=cancel, progress=progress)
        except RuntimeError as error:
            if 'H5Dopen' in str(error) and ('not found' in str(error) or "Can't open object" in str(error)):
                raise RuntimeError(
                    "This HDF5 recording is missing datasets required by the installed OpenEB converter. "
                    "H5 files can use different event layouts; the extension alone does not guarantee compatibility. "
                    "Prophesee precomputed HDF5 tensors (event cubes, histograms or time surfaces) "
                    "do not contain the original event tuples and cannot be imported as recordings. "
                    "Try the original DAT recording or a CSV export from the dataset provider. "
                    "The original file has not been modified.\n\nConverter details:\n" + str(error)
                ) from error
            raise
        if progress:
            progress(0, "Copying converted events back to Windows...")
        _wsl_stage_out_to_windows(wsl_csv, out_csv_path)
    finally:
        _run_wsl(f'rm -f -- {_shell_path(wsl_h5)} {_shell_path(wsl_csv)} {_shell_path(wsl_csv + ".sh")} {_shell_path(wsl_csv + ".fifo")}')

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

