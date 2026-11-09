"""
Helpers shared by the processor: writable caches on Lambda, threads from the cgroup quota, JSON that
never holds NaN, peak memory, the session contract of conventions.md (session_id from sessions.csv,
else sub-<a>_ses-<b>, else the file stem) and finding NWB files (HDF5 files and Zarr folders).

Nothing here imports numpy, h5py or pynwb at module level, so main() can set the thread and HDF5
variables before they load.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from pathlib import Path

SUB_SES_RE = re.compile(r"sub-([A-Za-z0-9-]+?)_ses-([A-Za-z0-9-]+)")
UUID_PREFIX_RE = re.compile(r"^([0-9a-fA-F]{8})-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"


def writable_caches() -> str:
    """Point every library cache at $TMPDIR (Lambda: only INPUT_DIR, OUTPUT_DIR, HOME and TMPDIR are
    writable, and nothing the image put in /tmp or HOME survives). Called before matplotlib is imported."""
    import tempfile

    # The Lambda runtime (and the brief's test recipe) may point HOME / TMPDIR at folders that do not exist yet.
    for var in ("TMPDIR", "HOME"):
        if os.environ.get(var):
            try:
                os.makedirs(os.environ[var], exist_ok=True)
            except OSError:
                pass
    tmp = os.environ.get("TMPDIR") or tempfile.gettempdir()
    for var, sub in (("MPLCONFIGDIR", "mpl"), ("XDG_CACHE_HOME", "cache")):
        if not os.environ.get(var) or not os.access(os.environ[var], os.W_OK):
            os.environ[var] = os.path.join(tmp, sub)
        os.makedirs(os.environ[var], exist_ok=True)
    if not os.environ.get("HOME") or not os.access(os.environ["HOME"], os.W_OK):
        os.environ["HOME"] = os.path.join(tmp, "home")
        os.makedirs(os.environ["HOME"], exist_ok=True)
    os.environ.setdefault("USER", "app")
    # Inputs are read-only (and on Lambda the whole file system is): HDF5 file locking would fail.
    os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
    # dandi: no version check against the network at import (etelemetry).
    os.environ.setdefault("DANDI_NO_ET", "1")
    return tmp


def cgroup_cpus() -> int:
    """CPUs from the cgroup quota (v2 cpu.max, v1 cfs), else the affinity mask; never the host's count alone."""
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            return max(1, math.floor(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    try:
        q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        per = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if q > 0 and per > 0:
            return max(1, q // per)
    except (OSError, ValueError):
        pass
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def set_threads(threads: int) -> int:
    n = threads if threads > 0 else cgroup_cpus()
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
        os.environ[var] = str(n)
    return n


def peak_rss_mb() -> float | None:
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except (ImportError, OSError):
        return None


def clean_json(obj):
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", "replace")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "tolist") and not isinstance(obj, (str, bytes)):
        try:
            return clean_json(obj.tolist())
        except (ValueError, AttributeError, TypeError):
            return str(obj)
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    return str(obj)


def write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean_json(data), fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def sanitise(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-") or "file"


def sub_ses_id(text: str) -> str | None:
    m = SUB_SES_RE.search(text)
    if not m:
        return None
    sub, ses = m.group(1), m.group(2)
    uuid = UUID_PREFIX_RE.match(ses)
    if uuid:
        ses = uuid.group(1)
    return f"sub-{sub}_ses-{ses}"


def nwb_stem(path: Path) -> str:
    name = path.name
    for ext in (".nwb.zarr", ".nwb", ".zarr", ".h5", ".hdf5"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def read_sheet(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]
    return [r for r in rows if r.get("session_id")]


class Sessions:
    """session_id resolution per conventions.md, "Sessions"."""

    def __init__(self, sheet_rows: list[dict] | None = None):
        self.rows = {}
        self._paths = []
        for r in sheet_rows or []:
            sid = sanitise(r["session_id"])
            self.rows.setdefault(sid, dict(r, session_id=sid))
            if r.get("path"):
                self._paths.append((r["path"].strip().strip("/"), sid))
        self._paths.sort(key=lambda t: -len(t[0]))

    def from_sheet(self, path: Path) -> str | None:
        parts = path.as_posix()
        for p, sid in self._paths:
            name = Path(p).name
            if path.name == name or f"/{p}" in f"/{parts}" or any(par.name == name for par in path.parents):
                return sid
        return None

    def session_id(self, path: Path) -> str:
        sid = self.from_sheet(path)
        if sid:
            return sid
        sid = sub_ses_id(path.name)
        if sid:
            return sid
        for parent in path.parents:
            sid = sub_ses_id(parent.name)
            if sid:
                return sid
        return sanitise(nwb_stem(path))

    def sheet_columns(self, sid: str) -> dict:
        row = self.rows.get(sid, {})
        return {k: v for k, v in row.items() if k not in ("session_id", "path")}


def is_hdf5(path: Path) -> bool:
    """HDF5 signature at offset 0 or at a user-block offset (512, 1024, ...)."""
    try:
        with open(path, "rb") as fh:
            offset = 0
            size = path.stat().st_size
            while offset < min(size, 1 << 20):
                fh.seek(offset)
                if fh.read(8) == HDF5_SIGNATURE:
                    return True
                offset = 512 if offset == 0 else offset * 2
    except OSError:
        return False
    return False


def is_zarr_nwb(path: Path) -> bool:
    """A Zarr folder (v2 .zgroup or v3 zarr.json) named *.nwb, *.nwb.zarr or *.zarr with NWB's root attributes."""
    name = path.name.lower()
    if not name.endswith((".nwb", ".zarr")):
        return False
    for meta in (".zattrs", "zarr.json"):
        f = path / meta
        if f.is_file():
            try:
                text = f.read_text(errors="replace")[:200000]
            except OSError:
                return False
            return "nwb_version" in text or '"core"' in text
    return False


def find_nwb(root: Path) -> tuple[list[tuple[Path, str]], list[Path]]:
    """Every NWB file under root, following symlinks (INPUT_DIR entries are symlinks), without loops.
    Returns ([(path, 'hdf5'|'zarr')], [paths named .nwb that are neither])."""
    found, rejected = [], []
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        keep = []
        for d in sorted(dirnames):
            if d.startswith("."):
                continue
            p = Path(dirpath) / d
            if is_zarr_nwb(p):
                found.append((p, "zarr"))
            else:
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            if f.startswith(".") or not f.lower().endswith(".nwb"):
                continue
            p = Path(dirpath) / f
            if is_hdf5(p):
                found.append((p, "hdf5"))
            else:
                rejected.append(p)
    return found, rejected


def find_sheet(root: Path) -> Path | None:
    for dirpath, _dirs, filenames in os.walk(root, followlinks=True):
        if "sessions.csv" in filenames:
            return Path(dirpath) / "sessions.csv"
    return None
