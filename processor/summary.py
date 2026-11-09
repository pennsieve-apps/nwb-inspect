"""
Content summary of one NWB file: session and subject, devices, electrode groups / probes, every
time series in acquisition, processing and stimulus (type, shape, rate or timestamps, unit), Units
(count, labels, brain areas), ophys (imaging planes, ROIs, series), ndx-pose (keypoints, frames),
interval tables (rows, columns), extensions, file size and the storage (chunking / compression) of
the largest datasets.

Reads attributes, shapes and small slices only (the first and last timestamp, label columns of at
most MAX_TABLE_ROWS rows), so it costs seconds even on a 50 GB file.
"""
from __future__ import annotations

import collections
import datetime as dt

import numpy as np

from .tree import Tree, _s

MAX_TABLE_ROWS = 200_000  # label / area columns of Units and electrodes are read when at most this long
LARGE_DATASET_MB = 50  # datasets this big are listed with their storage, uncompressed ones flagged
LABEL_COLUMNS = ("label", "quality", "bombcell_label", "unitrefine_label", "kslabel", "KSLabel", "default_qc",
                 "ibl_quality_score", "cell_type", "putative_cell_type")
AREA_COLUMNS = ("brain_area", "location", "brain_region", "acronym", "region", "allen_location",
                "beryl_location", "cosmos_location")
CORE_NAMESPACES = {"core", "hdmf-common", "hdmf-experimental"}


def _read_column(t: Tree, ds, limit=MAX_TABLE_ROWS):
    if ds is None or t.is_group(ds):
        return None
    shp = t.shape(ds)
    if len(shp) != 1 or shp[0] > limit:
        return None
    try:
        v = ds[:]
    except Exception:
        return None
    if v.dtype.kind in ("S", "O"):
        v = np.array([_s(x) for x in v], dtype=object)
    return v


def _counts(values, top=12):
    if values is None:
        return None
    def fmt(x):
        if isinstance(x, (float, np.floating)):
            return f"{x:.3g}"
        return str(x)

    c = collections.Counter(fmt(x) for x in values)
    return dict(c.most_common(top))


def _first_last(t: Tree, ds):
    """First and last value of a 1-d (or first column of 2-d) dataset: two tiny reads."""
    shp = t.shape(ds)
    if not shp or shp[0] == 0:
        return None, None
    try:
        a = ds[0] if len(shp) == 1 else ds[0, 0]
        b = ds[shp[0] - 1] if len(shp) == 1 else ds[shp[0] - 1, 0]
        return float(a), float(b)
    except Exception:
        return None, None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def timing(t: Tree, g) -> dict:
    """rate / timestamps of a TimeSeries group, from attributes and two reads."""
    out = {}
    data = g.get("data") if hasattr(g, "get") else None
    n = t.shape(data)[0] if data is not None and t.shape(data) else 0
    ts = g.get("timestamps") if hasattr(g, "get") else None
    st = g.get("starting_time") if hasattr(g, "get") else None
    if ts is not None and not t.is_group(ts):
        a, b = _first_last(t, ts)
        out.update(time_source="timestamps", n_timestamps=t.shape(ts)[0] if t.shape(ts) else 0, t_start=a, t_stop=b)
        if a is not None and b is not None and out["n_timestamps"] > 1 and b > a:
            out["rate_hz"] = round((out["n_timestamps"] - 1) / (b - a), 4)
    elif st is not None:
        rate = _float(t.attr(st, "rate"))
        t0 = _float(t.scalar(st))
        out.update(time_source="rate", rate_hz=rate, t_start=t0 if t0 is not None else 0.0)
        if rate:
            out["t_stop"] = out["t_start"] + n / float(rate)
    return out


def series_info(t: Tree, path: str, g) -> dict:
    data = g.get("data")
    info = {"path": path, "type": t.ntype(g), "shape": list(t.shape(data)) if data is not None else None,
            "dtype": t.dtype(data) if data is not None else None,
            "unit": t.attr(data, "unit") if data is not None else None}
    ext = g.get("external_file")
    if ext is not None:
        info["external_file"] = t.scalar(ext)
    info.update(timing(t, g))
    if info.get("t_start") is not None and info.get("t_stop") is not None:
        info["duration_s"] = round(info["t_stop"] - info["t_start"], 3)
    desc = t.attr(g, "description")
    if desc and desc != "no description":
        info["description"] = str(desc)[:200]
    return info


def _table_info(t: Tree, path: str, g) -> dict:
    ids = g.get("id")
    cols = t.attr(g, "colnames") or []
    return {"path": path, "type": t.ntype(g), "n_rows": t.shape(ids)[0] if ids is not None and t.shape(ids) else 0,
            "columns": [str(c) for c in (cols if isinstance(cols, list) else [cols])]}


def _units(t: Tree, g) -> dict:
    info = _table_info(t, "/units", g)
    st = g.get("spike_times")
    info["n_units"] = info.pop("n_rows")
    info["n_spikes"] = t.shape(st)[0] if st is not None and t.shape(st) else 0
    labels = {}
    for c in LABEL_COLUMNS:
        if c in info["columns"] and g.get(c) is not None:
            labels[c] = _counts(_read_column(t, g.get(c)))
    info["labels"] = labels
    for c in AREA_COLUMNS:
        if c in info["columns"]:
            info["brain_areas"] = _counts(_read_column(t, g.get(c)), top=20)
            info["brain_area_source"] = f"units.{c}"
            break
    if "brain_areas" not in info and "electrodes" in info["columns"]:
        # via the electrodes table (first electrode of each unit)
        el = t.get("general/extracellular_ephys/electrodes")
        loc = _read_column(t, el.get("location")) if el is not None and el.get("location") is not None else None
        reg = _read_column(t, g.get("electrodes"))
        idx = _read_column(t, g.get("electrodes_index"))
        if loc is not None and reg is not None:
            if idx is not None and len(idx) == info["n_units"]:
                starts = np.concatenate([[0], idx[:-1]]).astype(int)
                first = [reg[s] if s < len(reg) else None for s in starts]
            else:
                first = list(reg[: info["n_units"]])
            vals = [loc[int(i)] for i in first if i is not None and 0 <= int(i) < len(loc)]
            info["brain_areas"] = _counts(vals, top=20)
            info["brain_area_source"] = "electrodes.location of each unit's first electrode"
    if info["n_spikes"] and info["n_units"]:
        info["mean_spikes_per_unit"] = round(info["n_spikes"] / info["n_units"], 1)
    return info


def summarise(t: Tree, size_bytes: int) -> dict:
    s: dict = {"file_size_bytes": size_bytes, "format": t.fmt}
    root = t.root
    s["nwb_version"] = t.attr(root, "nwb_version")
    for k in ("identifier", "session_description", "session_start_time", "timestamps_reference_time"):
        s[k] = t.scalar(k)
    gen = {}
    for k in ("session_id", "lab", "institution", "experimenter", "experiment_description", "keywords",
              "related_publications", "protocol", "stimulus", "surgery", "virus", "data_collection"):
        v = t.scalar(f"general/{k}")
        if v not in (None, "", []):
            gen[k] = v if not isinstance(v, str) else v[:300]
    s["general"] = gen

    sub = t.get("general/subject")
    if sub is not None:
        subj = {"type": t.ntype(sub)}
        for k in ("subject_id", "species", "sex", "age", "date_of_birth", "genotype", "strain", "weight",
                  "description"):
            v = t.scalar(sub.get(k)) if sub.get(k) is not None else None
            if v not in (None, ""):
                subj[k] = v if not isinstance(v, str) else v[:200]
        if sub.get("age") is not None:
            ref = t.attr(sub.get("age"), "reference")
            if ref:
                subj["age_reference"] = ref
        s["subject"] = subj
    else:
        s["subject"] = None

    devices = []
    dev = t.get("general/devices")
    for k in t.keys(dev) if dev is not None else []:
        d = dev[k]
        rec = {"name": k, "type": t.ntype(d)}
        for a in ("description", "manufacturer", "model_number", "model_name", "serial_number"):
            v = t.attr(d, a)
            if v:
                rec[a] = str(v)[:200]
        devices.append(rec)
    s["devices"] = devices

    groups = []
    ece = t.get("general/extracellular_ephys")
    for k in t.keys(ece) if ece is not None else []:
        g = ece[k]
        if t.is_group(g) and t.ntype(g) == "ElectrodeGroup":
            groups.append({"name": k, "location": t.attr(g, "location"), "description": t.attr(g, "description"),
                           "device": t.child_name(g, "device")})
    s["electrode_groups"] = groups
    el = t.get("general/extracellular_ephys/electrodes")
    if el is not None:
        ei = _table_info(t, "/general/extracellular_ephys/electrodes", el)
        ei["locations"] = _counts(_read_column(t, el.get("location")), top=20) if el.get("location") is not None else None
        s["electrodes"] = ei

    # every typed object
    objs = t.walk()
    series, tables, intervals, pose, planes, segs, images = [], [], [], [], [], [], []
    for path, g in objs:
        typ = t.ntype(g) or ""
        if path.startswith("/general/") and typ not in ("ImagingPlane",):
            continue
        has_data = g.get("data") is not None and not t.is_group(g.get("data"))
        has_time = g.get("timestamps") is not None or g.get("starting_time") is not None
        if typ == "PoseEstimation":
            kp = []
            n_frames = None
            for k in t.keys(g):
                c = g[k]
                if t.is_group(c) and t.ntype(c) == "PoseEstimationSeries":
                    kp.append(k)
                    if n_frames is None and c.get("data") is not None:
                        n_frames = t.shape(c.get("data"))[0]
            first = g[kp[0]] if kp else None
            rec = {"path": path, "keypoints": kp, "n_keypoints": len(kp), "n_frames": n_frames,
                   "source_software": t.scalar(g.get("source_software")) if g.get("source_software") is not None
                   else t.attr(g, "source_software"),
                   "scorer": t.scalar(g.get("scorer")) if g.get("scorer") is not None else t.attr(g, "scorer")}
            if first is not None:
                rec.update({k: v for k, v in timing(t, first).items() if k in ("rate_hz", "t_start", "t_stop",
                                                                                 "time_source")})
            pose.append(rec)
        elif has_data and has_time:
            if typ == "PoseEstimationSeries":
                continue  # summarised with its PoseEstimation
            series.append(series_info(t, path, g))
        elif typ == "TimeIntervals":
            ti = _table_info(t, path, g)
            ti["n_intervals"] = ti.pop("n_rows")
            stt, sto = g.get("start_time"), g.get("stop_time")
            if stt is not None:
                ti["t_start"] = _first_last(t, stt)[0]
            if sto is not None:
                col = _read_column(t, sto)
                ti["t_stop"] = float(np.nanmax(col)) if col is not None and len(col) else _first_last(t, sto)[1]
            intervals.append(ti)
        elif typ == "ImagingPlane":
            rec = {"path": path, "location": t.attr(g, "location"), "indicator": t.attr(g, "indicator"),
                   "excitation_lambda": t.attr(g, "excitation_lambda"), "description": t.attr(g, "description"),
                   "device": t.child_name(g, "device")}
            for k in ("imaging_rate", "location", "indicator", "excitation_lambda", "description"):
                if g.get(k) is not None:
                    rec[k] = t.scalar(g.get(k))
            planes.append(rec)
        elif typ == "PlaneSegmentation":
            ps = _table_info(t, path, g)
            ps["n_rois"] = ps.pop("n_rows")
            for c in ("accepted", "iscell", "is_cell"):
                if c in ps["columns"]:
                    col = _read_column(t, g.get(c))
                    if col is not None and col.dtype.kind in "biuf":
                        ps[f"n_{c}"] = int(np.sum(np.asarray(col, dtype=float) > 0.5)) if col.ndim == 1 else None
            segs.append(ps)
        elif typ in ("Units",) and path == "/units":
            pass
        elif t.attr(g, "colnames") is not None and g.get("id") is not None:
            tables.append(_table_info(t, path, g))
        elif typ in ("Images", "GrayscaleImage", "RGBImage", "Image"):
            images.append({"path": path, "type": typ})

    s["time_series"] = series
    s["pose"] = pose
    s["intervals"] = intervals
    s["ophys"] = {"imaging_planes": planes, "plane_segmentations": segs,
                  "roi_response_series": [x for x in series if x["type"] == "RoiResponseSeries"],
                  "imaging_series": [x for x in series if x["type"] in ("TwoPhotonSeries", "OnePhotonSeries")]}
    s["tables"] = tables
    s["images"] = images[:20]
    for x in intervals:
        if x["path"] == "/intervals/trials":
            s["trials"] = {"n_trials": x["n_intervals"], "columns": x["columns"]}
    units = t.get("units")
    s["units"] = _units(t, units) if units is not None and t.is_group(units) else None

    spec = t.specifications()
    s["namespaces"] = spec
    s["extensions"] = {k: v for k, v in spec.items() if k not in CORE_NAMESPACES}

    # session span from the series and intervals (units are not read: spike_times can be huge)
    starts = [x.get("t_start") for x in series + intervals + pose if x.get("t_start") is not None]
    stops = [x.get("t_stop") for x in series + intervals + pose if x.get("t_stop") is not None]
    if starts and stops:
        s["t_start"] = float(min(starts))
        s["t_stop"] = float(max(stops))
        s["duration_s"] = round(s["t_stop"] - s["t_start"], 3)

    # storage of the largest datasets
    rows = []
    for p, ds in t.datasets():
        try:
            shp = ds.shape
            n = int(np.prod(shp)) * ds.dtype.itemsize if shp else 0
        except Exception:
            continue
        if n >= 1 << 20:
            rows.append((n, p, ds))
    rows.sort(key=lambda r: -r[0])
    big = []
    for n, p, ds in rows[:15]:
        info = t.storage(ds)
        info["path"] = p
        if info.get("stored_bytes"):
            info["compression_ratio"] = round(info["nbytes"] / max(info["stored_bytes"], 1), 2)
        info["flag_uncompressed_large"] = bool(info["nbytes"] >= LARGE_DATASET_MB * (1 << 20)
                                               and not info.get("compression"))
        big.append(info)
    s["largest_datasets"] = big
    s["n_datasets_over_1mb"] = len(rows)
    return s


def headline(s: dict) -> dict:
    """Small numbers for summary.json / the cover page."""
    u = s.get("units") or {}
    sub = s.get("subject") or {}
    h = {
        "nwb_version": s.get("nwb_version"),
        "identifier": s.get("identifier"),
        "session_start_time": s.get("session_start_time"),
        "duration_s": s.get("duration_s"),
        "subject_id": sub.get("subject_id"),
        "species": sub.get("species"),
        "n_units": u.get("n_units"),
        "n_time_series": len(s.get("time_series") or []),
        "n_rois": sum(x.get("n_rois") or 0 for x in (s.get("ophys") or {}).get("plane_segmentations", [])),
        "n_keypoints": sum(x.get("n_keypoints") or 0 for x in s.get("pose") or []),
        "n_trials": (s.get("trials") or {}).get("n_trials"),
        "extensions": sorted((s.get("extensions") or {}).keys()),
        "file_size_mb": round((s.get("file_size_bytes") or 0) / 1e6, 1),
    }
    return h


def describe_age(s: dict) -> str | None:
    sub = s.get("subject") or {}
    if sub.get("age"):
        return str(sub["age"])
    dob = sub.get("date_of_birth")
    st = s.get("session_start_time")
    if dob and st:
        try:
            d = dt.datetime.fromisoformat(str(dob))
            t = dt.datetime.fromisoformat(str(st))
            return f"{(t - d).days} days (from date_of_birth)"
        except ValueError:
            return None
    return None
