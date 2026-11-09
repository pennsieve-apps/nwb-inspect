"""
nwb-inspect: is this NWB file valid, does it follow best practices, is it ready for DANDI, and what
is in it?

For every NWB file under INPUT_DIR (HDF5 .nwb files and NWB-Zarr folders, found recursively,
following symlinks): PyNWB schema validation, NWB Inspector, DANDI upload readiness (offline), a
content summary and, with PREVIEWS=true, small previews. Writes, under OUTPUT_DIR/nwb-inspect/
[LABEL/]: report.json, report.pdf, issues.csv, summary.json, provenance.json and the preview PNGs.

Exit codes: 0 ok; 1 no NWB file found, every file unreadable, or (FAIL_ON=critical) at least one file
with status fail; 2 bad parameters.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
import os
import sys
import time
import traceback
import warnings
from pathlib import Path

from . import common

APP = "nwb-inspect"
CHECK_NAMES = ("schema", "inspector", "dandi")
THRESHOLDS = ("BEST_PRACTICE_SUGGESTION", "BEST_PRACTICE_VIOLATION", "CRITICAL")
CITATIONS = ["10.7554/eLife.78362", "10.1109/BigData47090.2019.9005648", "10.5281/zenodo.10611726",
             "10.5281/zenodo.3692138"]

log = logging.getLogger(APP)


class ParamError(ValueError):
    pass


def params_from_env(env=os.environ) -> dict:
    def get(name, default):
        v = env.get(name)
        return default if v is None or str(v).strip() == "" else str(v).strip()

    p = {}
    raw = get("CHECKS", "schema,inspector,dandi").lower()
    checks = [] if raw == "none" else [c.strip() for c in raw.split(",") if c.strip()]
    bad = [c for c in checks if c not in CHECK_NAMES]
    if bad:
        raise ParamError(f"CHECKS: unknown check(s) {bad}; use a comma-separated subset of {', '.join(CHECK_NAMES)}")
    p["CHECKS"] = ",".join(c for c in CHECK_NAMES if c in checks)
    p["INSPECTOR_CONFIG"] = get("INSPECTOR_CONFIG", "dandi").lower()
    if p["INSPECTOR_CONFIG"] not in ("dandi", "default"):
        raise ParamError("INSPECTOR_CONFIG must be dandi or default")
    p["IMPORTANCE_THRESHOLD"] = get("IMPORTANCE_THRESHOLD", "BEST_PRACTICE_SUGGESTION").upper()
    if p["IMPORTANCE_THRESHOLD"] not in THRESHOLDS:
        raise ParamError(f"IMPORTANCE_THRESHOLD must be one of {', '.join(THRESHOLDS)}")
    p["FAIL_ON"] = get("FAIL_ON", "none").lower()
    if p["FAIL_ON"] not in ("none", "critical"):
        raise ParamError("FAIL_ON must be none or critical")
    pv = get("PREVIEWS", "true").lower()
    if pv not in ("true", "false", "1", "0", "yes", "no"):
        raise ParamError("PREVIEWS must be true or false")
    p["PREVIEWS"] = pv in ("true", "1", "yes")
    p["LABEL"] = common.sanitise(get("LABEL", "")) if get("LABEL", "") else ""
    try:
        p["THREADS"] = int(get("THREADS", "0"))
    except ValueError:
        raise ParamError("THREADS must be an integer")
    if p["THREADS"] < 0:
        raise ParamError("THREADS must be >= 0")
    return p


def status_of(counts: dict, unreadable: bool) -> str:
    if unreadable or counts.get("CRITICAL"):
        return "fail"
    if counts.get("BEST_PRACTICE_VIOLATION") or counts.get("ERROR"):
        return "warn"
    return "pass"


def tool_versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for pkg in ("pynwb", "hdmf", "nwbinspector", "dandi", "dandischema", "h5py", "hdmf-zarr", "zarr", "numpy",
                "matplotlib"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            pass
    return out


def inspect_file(path: Path, fmt: str, rel: str, p: dict, out_dir: Path, file_id: str) -> tuple[dict, list]:
    from . import checks as ck
    from .summary import headline, summarise
    from .tree import Tree

    checks = p["CHECKS"].split(",") if p["CHECKS"] else []
    t0 = time.time()
    rec = {"file": rel, "file_id": file_id, "format": fmt, "size_bytes": None, "status": None, "dandi_ready": None,
           "counts": {}, "messages": [], "summary": None, "dandi": None, "schema": None, "previews": [],
           "error": None, "timings_s": {}}
    try:
        rec["size_bytes"] = path.stat().st_size if fmt == "hdf5" else sum(
            f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        pass
    msgs = []
    unreadable = False

    if "schema" in checks:
        t = time.time()
        sm, info = ck.run_schema(path)
        rec["schema"] = info
        msgs += sm
        unreadable |= any(m["check_name"] == "schema.read_error" for m in sm)
        rec["timings_s"]["schema"] = round(time.time() - t, 2)

    insp = None
    if "inspector" in checks and not unreadable:
        t = time.time()
        insp = ck.run_inspector(path, fmt, p["INSPECTOR_CONFIG"], p["IMPORTANCE_THRESHOLD"])
        msgs += insp
        rec["timings_s"]["inspector"] = round(time.time() - t, 2)

    if "dandi" in checks and not unreadable:
        t = time.time()
        try:
            dm, dinfo = ck.run_dandi(path, fmt, insp, p["INSPECTOR_CONFIG"], p["IMPORTANCE_THRESHOLD"])
        except Exception as e:
            dm, dinfo = [ck.issue("dandi", "ERROR", "dandi.error", f"{type(e).__name__}: {e}")], {}
        msgs += dm
        rec["dandi"] = dinfo
        rec["timings_s"]["dandi"] = round(time.time() - t, 2)

    figs = []
    t = time.time()
    try:
        with Tree(path, fmt) as tree:
            rec["summary"] = summarise(tree, rec["size_bytes"] or 0)
            rec["timings_s"]["summary"] = round(time.time() - t, 2)
            if p["PREVIEWS"]:
                tp = time.time()
                figs = make_previews(tree, rec["summary"], out_dir, file_id)
                rec["timings_s"]["previews"] = round(time.time() - tp, 2)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        log.warning("%s: summary failed: %s", rel, rec["error"])
        log.debug(traceback.format_exc())
        if "schema" not in checks:
            unreadable = True
    rec["previews"] = [{"path": f.name, "caption": c} for f, c in figs]

    # IMPORTANCE_THRESHOLD applies to every check group (ERROR = a check could not run, always kept).
    thr = ck.IMPORTANCE_RANK[p["IMPORTANCE_THRESHOLD"]]
    msgs = [m for m in msgs if ck.IMPORTANCE_RANK.get(m["importance"], 3) >= thr]
    rec["messages"] = msgs
    rec["_unreadable"] = unreadable
    if unreadable and not rec["error"]:
        rec["error"] = next((m["message"] for m in msgs if m["check_name"].endswith("read_error")), "unreadable")
    recount(rec)
    if "dandi" in checks:
        # As `dandi validate` / `dandi upload`: schema errors, every NWB Inspector CRITICAL or ERROR under
        # the DANDI configuration (marked dandi_blocking by checks.run_dandi), and DANDI's own metadata errors.
        rec["dandi_ready"] = bool(not unreadable and not any(
            m.get("dandi_blocking") or (m["check_group"] in ("schema", "dandi") and m["importance"] in ("CRITICAL", "ERROR"))
            for m in msgs))
        if "schema" not in checks:
            rec["dandi_ready_note"] = "schema validation was not run (CHECKS)"
    rec["headline"] = headline(rec["summary"]) if rec["summary"] else {}
    rec["seconds"] = round(time.time() - t0, 2)
    return rec, figs


def recount(rec: dict) -> None:
    """counts, counts_by_group and status from rec["messages"]."""
    counts = {k: 0 for k in ("CRITICAL", "BEST_PRACTICE_VIOLATION", "BEST_PRACTICE_SUGGESTION", "ERROR")}
    by_group: dict = {}
    for m in rec["messages"]:
        counts[m["importance"]] = counts.get(m["importance"], 0) + 1
        by_group[m["check_group"]] = by_group.get(m["check_group"], 0) + 1
    rec["counts"] = counts
    rec["counts_by_group"] = by_group
    rec["status"] = status_of(counts, rec.get("_unreadable", False))


def check_unique_identifiers(files: list[dict], threshold: str) -> int:
    """NWB Inspector's folder-level check (CRITICAL when it inspects a folder): every NWB file needs its own
    identifier. Inspection here runs file by file, so it is applied across all files of the run. Not
    DANDI-blocking: `dandi validate` checks files one at a time and does not run it."""
    from . import checks as ck

    if ck.IMPORTANCE_RANK["CRITICAL"] < ck.IMPORTANCE_RANK[threshold]:
        return 0
    by_id: dict = {}
    for f in files:
        ident = ((f.get("summary") or {}).get("identifier"))
        if ident:
            by_id.setdefault(str(ident), []).append(f)
    n = 0
    for ident, group in by_id.items():
        if len(group) < 2:
            continue
        names = sorted(f["file"] for f in group)
        for f in group:
            others = [x for x in names if x != f["file"]]
            f["messages"].append(ck.issue(
                "inspector", "CRITICAL", "check_unique_identifiers",
                f"The identifier '{ident}' is also used by {len(others)} other file(s) in this input: "
                f"{', '.join(others[:5])}{' ...' if len(others) > 5 else ''}. The identifier of every NWBFile must "
                "be unique (a new UUID per file); derived files should not copy their source's identifier.",
                object_type="NWBFile", object_name="root", location="/"))
            recount(f)
            n += 1
    return n


def make_previews(tree, summary: dict, out_dir: Path, file_id: str):
    import matplotlib.pyplot as plt

    from .previews import PREVIEWS

    out = []
    for what, fn in PREVIEWS:
        t = time.time()
        try:
            res = fn(tree, summary, file_id if len(file_id) <= 34 else file_id[:33] + "…")
        except Exception as e:
            log.warning("%s: %s preview failed: %s: %s", file_id, what, type(e).__name__, e)
            log.debug(traceback.format_exc())
            plt.close("all")
            continue
        if res is None:
            continue
        fig, cap = res
        png = out_dir / f"{file_id}_{what}.png"
        fig.savefig(png, dpi=150)
        plt.close(fig)
        out.append((png, cap))
        log.debug("%s: %s preview %.1f s", file_id, what, time.time() - t)
    return out


def write_issues_csv(path: Path, files: list[dict], sessions: dict):
    cols = ["file", "file_id", "session_id", "status", "check_group", "importance", "check_name", "object_type",
            "object_name", "location", "message"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for f in files:
            for m in f["messages"]:
                w.writerow({"file": f["file"], "file_id": f["file_id"], "session_id": f["session_id"],
                            "status": f["status"], **{k: m.get(k, "") for k in cols[4:]}})


def main(argv=None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("dandi", "hdmf", "pynwb", "nwbinspector", "matplotlib", "h5py", "numcodecs", "zarr"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore")
    started = dt.datetime.now(dt.timezone.utc)
    t_start = time.time()
    try:
        p = params_from_env()
    except ParamError as e:
        log.error("bad parameters: %s", e)
        return 2
    common.writable_caches()
    threads = common.set_threads(p["THREADS"])
    os.environ.setdefault("MPLBACKEND", "Agg")

    in_dir = Path(os.environ.get("INPUT_DIR", "/data/input"))
    out_root = Path(os.environ.get("OUTPUT_DIR", "/data/output"))
    out_dir = out_root / APP / p["LABEL"] if p["LABEL"] else out_root / APP
    out_dir.mkdir(parents=True, exist_ok=True)
    version = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip() \
        if (Path(__file__).resolve().parent.parent / "VERSION").exists() else "0.0.0"
    log.info("nwb-inspect %s: INPUT_DIR=%s OUTPUT_DIR=%s threads=%d %s", version, in_dir, out_dir, threads,
             " ".join(f"{k}={v}" for k, v in p.items()))

    found, rejected = common.find_nwb(in_dir)
    for r in rejected:
        log.warning("%s: named .nwb but not an HDF5 file; skipped", r)
    if not found:
        log.error("no NWB file (.nwb HDF5 file or NWB-Zarr folder) under %s", in_dir)
        return 1
    sheet = common.find_sheet(in_dir)
    sessions = common.Sessions(common.read_sheet(sheet) if sheet else [])
    log.info("found %d NWB file(s)%s", len(found), f"; sessions sheet {sheet}" if sheet else "")

    sids = [sessions.session_id(pth) for pth, _ in found]
    files, figures = [], {}
    used = set()
    for i, ((pth, fmt), sid) in enumerate(zip(found, sids), 1):
        file_id = sid if sids.count(sid) == 1 else common.sanitise(common.nwb_stem(pth))
        base, k = file_id, 2
        while file_id in used:
            file_id, k = f"{base}-{k}", k + 1
        used.add(file_id)
        try:
            rel = str(pth.relative_to(in_dir))
        except ValueError:
            rel = str(pth)
        try:
            rec, figs = inspect_file(pth, fmt, rel, p, out_dir, file_id)
        except Exception as e:  # never lose the whole run to one file
            log.error("%s: inspection crashed: %s", rel, e)
            log.debug(traceback.format_exc())
            rec, figs = {"file": rel, "file_id": file_id, "format": fmt, "status": "fail", "dandi_ready": False,
                         "counts": {"CRITICAL": 0}, "messages": [], "summary": None, "error": f"{type(e).__name__}: {e}",
                         "previews": [], "headline": {}, "seconds": 0}, []
        rec["session_id"] = sid
        rec["sheet"] = sessions.sheet_columns(sid)
        files.append(rec)
        figures[file_id] = [(str(f), c) for f, c in figs]
        c = rec["counts"]
        log.info("[%d/%d] %s: status=%s critical=%d violations=%d suggestions=%d check_errors=%d dandi_ready=%s "
                 "previews=%d %.1f s%s", i, len(found), rel, rec["status"], c.get("CRITICAL", 0),
                 c.get("BEST_PRACTICE_VIOLATION", 0), c.get("BEST_PRACTICE_SUGGESTION", 0), c.get("ERROR", 0),
                 rec.get("dandi_ready"), len(figs), rec.get("seconds", 0),
                 f" error={rec['error']}" if rec.get("error") else "")

    n_dup = check_unique_identifiers(files, p["IMPORTANCE_THRESHOLD"])
    if n_dup:
        log.warning("check_unique_identifiers: %d file(s) share their identifier with another file", n_dup)
    for f in files:
        f.pop("_unreadable", None)

    tools = tool_versions()
    generated = dt.datetime.now(dt.timezone.utc).isoformat()
    report = {"app": APP, "version": version, "generated": generated, "parameters": p, "tools": tools,
              "n_files": len(files),
              "n_status": {k: sum(1 for f in files if f["status"] == k) for k in ("pass", "warn", "fail")},
              "n_dandi_ready": sum(1 for f in files if f.get("dandi_ready")),
              "files": files}
    common.write_json(out_dir / "report.json", report)
    write_issues_csv(out_dir / "issues.csv", files, sessions)
    try:
        from .report_pdf import write_pdf

        write_pdf(out_dir / "report.pdf", report, figures)
    except Exception as e:
        log.error("report.pdf failed: %s", e)
        log.debug(traceback.format_exc())

    # summary.json for neuro-report
    warn = []
    for f in files:
        if f["status"] == "fail":
            crit = [m for m in f["messages"] if m["importance"] == "CRITICAL"]
            what = "; ".join(sorted({m["check_name"] for m in crit})[:5]) or f.get("error") or ""
            warn.append(f"{f['file_id']}: fail ({what})")
    summary = {"app": APP, "version": version,
               "sessions": {f["file_id"]: {"file": f["file"], "session_id": f["session_id"], "status": f["status"],
                                           "dandi_ready": f.get("dandi_ready"),
                                           "n_critical": f["counts"].get("CRITICAL", 0),
                                           "n_violations": f["counts"].get("BEST_PRACTICE_VIOLATION", 0),
                                           "n_suggestions": f["counts"].get("BEST_PRACTICE_SUGGESTION", 0),
                                           "suggested_dandi_path": (f.get("dandi") or {}).get("suggested_path"),
                                           **{k: v for k, v in (f.get("headline") or {}).items()},
                                           **(f.get("sheet") or {})}
                            for f in files},
               "n_files": len(files), "n_pass": report["n_status"]["pass"], "n_warn": report["n_status"]["warn"],
               "n_fail": report["n_status"]["fail"], "n_dandi_ready": report["n_dandi_ready"],
               "figures": [{"path": pv["path"], "caption": pv["caption"]} for f in files for pv in f["previews"]],
               "tables": ["issues.csv", "report.json", "report.pdf"],
               "warnings": warn}
    common.write_json(out_dir / "summary.json", summary)

    finished = dt.datetime.now(dt.timezone.utc)
    prov = {"app": APP, "version": version, "variant": None, "tools": tools,
            "parameters": {k: v for k, v in p.items()}, "inputs": [f["file"] for f in files],
            "started": started.isoformat(), "finished": finished.isoformat(),
            "wall_seconds": round(time.time() - t_start, 2), "peak_rss_mb": common.peak_rss_mb(), "gpu": None,
            "sessions": {f["file_id"]: {"status": "failed" if f.get("error") and not f.get("summary") else "ok",
                                        "inspection_status": f["status"], "seconds": f.get("seconds")} for f in files},
            "citations": CITATIONS}
    common.write_json(out_dir / "provenance.json", prov)

    n_unreadable = sum(1 for f in files if f.get("error") and f["status"] == "fail" and not f.get("summary"))
    log.info("done: %d file(s): %d pass, %d warn, %d fail; %d DANDI-ready; %.1f s, peak RSS %s MB",
             len(files), report["n_status"]["pass"], report["n_status"]["warn"], report["n_status"]["fail"],
             report["n_dandi_ready"], time.time() - t_start, common.peak_rss_mb())
    if n_unreadable == len(files):
        log.error("no file could be read")
        return 1
    if p["FAIL_ON"] == "critical" and report["n_status"]["fail"]:
        log.error("FAIL_ON=critical: %d file(s) have critical problems: %s", report["n_status"]["fail"],
                  ", ".join(f["file_id"] for f in files if f["status"] == "fail"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
