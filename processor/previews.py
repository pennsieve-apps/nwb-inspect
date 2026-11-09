"""
Bounded previews of what is in an NWB file (PREVIEWS=true): a 60 s spike raster, a few ΔF/F traces,
one pose frame, and a timeline of the interval tables (trials, epochs, ...). Each reads small slices
only: at most MAX_UNITS units' spike trains (and at most MAX_SPIKES spike times in total), a window of
at most MAX_SAMPLES samples of MAX_ROIS ROIs, one frame of each keypoint plus a short trajectory,
and at most MAX_INTERVALS rows per interval table.

Each preview returns (figure, caption) or None; main.py saves them as PNG and puts them in the PDF.
"""
from __future__ import annotations

import numpy as np

from .tree import Tree, _s

MAX_UNITS = 150
MAX_SPIKES = 200_000_000  # spike_times read in BLOCK-sized pieces; beyond this, later spikes are not read
BLOCK = 2_500_000  # 20 MB of float64 per read
RASTER_WINDOW_S = 60.0
MAX_ROIS = 8
MAX_ROI_SCAN = 64
MAX_SAMPLES = 6000
TRACE_WINDOW_S = 120.0
TRAJ_FRAMES = 600
MAX_INTERVALS = 20_000
MAX_TABLES = 8

INK = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#2563eb"
PALETTE = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"]


def _fig(w=7.2, h=3.2):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=7, colors=INK)
    return fig, ax


# ---------------------------------------------------------------------------------------------- raster
def raster(t: Tree, s: dict, title: str):
    g = t.get("units")
    if g is None or not (s.get("units") or {}).get("n_units"):
        return None
    st, idx = g.get("spike_times"), g.get("spike_times_index")
    if st is None:
        return None
    n_spk = t.shape(st)[0] if t.shape(st) else 0
    if n_spk == 0:
        return None
    if idx is not None:
        ends = np.asarray(idx[:], dtype=np.int64)
    else:
        ends = np.array([n_spk], dtype=np.int64)
    starts = np.concatenate([[0], ends[:-1]])
    counts = ends - starts
    n_units = len(ends)
    # Prefer units labelled good when a label column says so.
    order = np.arange(n_units)
    label = None
    for c in ("label", "bombcell_label", "quality", "kslabel", "KSLabel"):
        if g.get(c) is not None and t.shape(g.get(c)) == (n_units,):
            label = np.array([_s(x) for x in g.get(c)[:]], dtype=object)
            break
    chosen = order[counts > 0]
    note = ""
    if label is not None:
        good = chosen[np.isin(label[chosen].astype(str), ["good", "sua", "1"])]
        if len(good) >= 10:
            chosen, note = good, " labelled good"
    if len(chosen) > MAX_UNITS:
        chosen = np.sort(np.random.default_rng(0).choice(chosen, MAX_UNITS, replace=False))
    # The window: the middle 60 s of the file's data span (series and intervals, from the summary); when the file
    # has neither, the middle of the first unit's spike train (its first and last spike).
    if s.get("t_start") is not None and s.get("t_stop") is not None:
        mid = (s["t_start"] + s["t_stop"]) / 2
    else:
        a, b = float(st[0]), float(st[min(n_spk - 1, int(ends[0]) - 1)])
        mid = (a + b) / 2
    t0 = mid - RASTER_WINDOW_S / 2
    t1 = t0 + RASTER_WINDOW_S
    # Read spike_times in blocks (one pass, bounded memory) and keep the chosen units' spikes in the window.
    chosen = np.sort(chosen)
    want = {int(u): [] for u in chosen}
    block = BLOCK
    for b0 in range(0, min(n_spk, MAX_SPIKES), block):
        b1 = min(b0 + block, n_spk)
        lo = np.searchsorted(ends, b0, side="right")
        hi = np.searchsorted(starts, b1, side="left")
        sel = chosen[(chosen >= lo) & (chosen < hi)]
        if not len(sel):
            continue
        x = np.asarray(st[b0:b1], dtype=float)
        for u in sel:
            a, b = max(int(starts[u]), b0) - b0, min(int(ends[u]), b1) - b0
            v = x[a:b]
            want[int(u)].append(v[(v >= t0) & (v < t1)])
    trains = [(u, np.concatenate(v) if v else np.empty(0)) for u, v in want.items()]
    if not trains:
        return None
    if all(len(x) == 0 for _, x in trains):
        return None  # no chosen unit fires in that window: no raster rather than an empty one
    # Order rows by depth when the table has it.
    depth = None
    for c in ("depth", "peak_channel_depth", "y", "peak_channel", "max_electrode", "peak_channel_id"):
        if g.get(c) is not None and t.shape(g.get(c)) == (n_units,):
            try:
                depth = np.asarray(g.get(c)[:], dtype=float)
                break
            except (TypeError, ValueError):
                depth = None
    if depth is not None:
        trains.sort(key=lambda x: depth[x[0]])
    fig, ax = _fig(7.2, 3.6)
    rows, n_in = [], 0
    for i, (_u, x) in enumerate(trains):
        w = x[(x >= t0) & (x < t1)]
        n_in += len(w)
        rows.append(w)
    ax.eventplot(rows, colors=INK, linelengths=0.8, linewidths=0.4)
    ax.set_xlim(t0, t1)
    ax.set_ylim(-1, len(rows))
    ax.set_xlabel("time (s, session clock)", fontsize=8)
    ax.set_ylabel("unit" + (" (sorted by depth)" if depth is not None else ""), fontsize=8)
    ax.set_title(f"{title}: spike raster", fontsize=9, color=INK)
    fig.tight_layout()
    cap = (f"Spike raster of {len(rows)} of {n_units} units{note} in a {RASTER_WINDOW_S:.0f} s window "
           f"({t0:.1f}-{t1:.1f} s on the session clock; {n_in:,} spikes). Each row is a unit, each tick a "
           "spike. Look for rows that go silent part-way (a lost unit or drift), vertical stripes through "
           "every unit at once (shared noise artefacts) and empty stretches (gaps in the recording).")
    return fig, cap


# ------------------------------------------------------------------------------------------------ ophys
def _roi_series(s: dict):
    rrs = (s.get("ophys") or {}).get("roi_response_series") or []
    for key in ("dfoverf", "dff", "df_over_f"):
        for x in rrs:
            if key in x["path"].lower().replace("/", "").replace("_", "") or key in x["path"].lower():
                return x, "ΔF/F"
    for x in rrs:
        if "fluorescence" in x["path"].lower():
            return x, "fluorescence"
    return (rrs[0], "ROI response") if rrs else (None, None)


def traces(t: Tree, s: dict, title: str):
    x, kind = _roi_series(s)
    if x is None or not x.get("shape") or len(x["shape"]) < 2:
        return None
    g = t.get(x["path"])
    data = g.get("data")
    n_t, n_roi = x["shape"][0], x["shape"][1]
    rate = x.get("rate_hz") or 30.0
    n = int(min(MAX_SAMPLES, max(10, TRACE_WINDOW_S * rate), n_t))
    i0 = max(0, n_t // 2 - n // 2)
    # the most active of the first MAX_ROI_SCAN ROIs in the window (robust spread / median)
    m = min(MAX_ROI_SCAN, n_roi)
    y = np.asarray(data[i0:i0 + n, :m], dtype=float)
    with np.errstate(all="ignore"):
        spread = np.nanpercentile(y, 99, axis=0) - np.nanpercentile(y, 50, axis=0)
        noise = np.nanmedian(np.abs(np.diff(y, axis=0)), axis=0) + 1e-12
    score = np.where(np.isfinite(spread / noise), spread / noise, -1)
    pick = np.sort(np.argsort(-score)[: min(MAX_ROIS, m)])
    y = y[:, pick]
    k = len(pick)
    ts = g.get("timestamps")
    if ts is not None:
        tt = np.asarray(ts[i0:i0 + n], dtype=float)
    else:
        tt = (x.get("t_start") or 0.0) + (i0 + np.arange(n)) / rate
    fig, ax = _fig(7.2, 3.6)
    off = 0.0
    for j in range(k):
        v = y[:, j]
        if not np.isfinite(v).any():
            continue
        lo, hi = np.nanpercentile(v, 1), np.nanmax(v)
        span = (hi - lo) or 1.0
        ax.plot(tt, (v - lo) / span + off, lw=0.6, color=PALETTE[j % len(PALETTE)])
        ax.text(tt[0], off + 0.5, f"ROI {pick[j]} ", fontsize=6, ha="right", va="center", color=MUTED)
        off += 1.2
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("time (s, session clock)", fontsize=8)
    ax.set_title(f"{title}: {kind} traces", fontsize=9, color=INK)
    fig.tight_layout()
    cap = (f"{kind} of the {k} most active of the first {m} of {n_roi} ROIs in {x['path']} over {tt[-1] - tt[0]:.0f} s from the middle "
           "of the recording, each scaled from its 1st percentile to its maximum. Look for sharp transients "
           "rising quickly and decaying over about a second (calcium events), slow drifts or steps (motion or "
           "neuropil problems) and traces that are flat or pure noise.")
    return fig, cap


# ------------------------------------------------------------------------------------------------- pose
def pose_frame(t: Tree, s: dict, title: str):
    pe = (s.get("pose") or [])
    pe = [p for p in pe if p.get("n_keypoints") and p.get("n_frames")]
    if not pe:
        return None
    p = max(pe, key=lambda r: r["n_keypoints"])
    g = t.get(p["path"])
    n = p["n_frames"]
    pts, names, conf = [], [], []
    # pick a frame in the middle where most keypoints are present
    frame = None
    for cand in (n // 2, n // 3, 2 * n // 3, n // 4, 3 * n // 4, 0):
        vals = []
        for k in p["keypoints"]:
            d = g[k].get("data")
            vals.append(np.asarray(d[cand], dtype=float)[:2])
        ok = sum(np.isfinite(v).all() for v in vals)
        if frame is None or ok > frame[1]:
            frame = (cand, ok, vals)
        if ok == len(vals):
            break
    i, _ok, vals = frame
    for k, v in zip(p["keypoints"], vals):
        names.append(k.replace("PoseEstimationSeries", ""))
        pts.append(v)
        c = g[k].get("confidence")
        try:
            conf.append(float(c[i]) if c is not None else np.nan)
        except Exception:
            conf.append(np.nan)
    pts = np.array(pts)
    first = g[p["keypoints"][0]].get("data")
    unit = str(t.attr(first, "unit") or "").strip()
    image_coords = unit.lower() in ("pixels", "pixel", "px", "")
    a, b = max(0, i - TRAJ_FRAMES // 2), min(n, i + TRAJ_FRAMES // 2)
    traj = np.asarray(first[a:b], dtype=float)[:, :2]
    fig, ax = _fig(5.4, 4.2)
    traj = np.where(np.all(traj == 0, axis=1, keepdims=True), np.nan, traj)  # (0, 0) = "not tracked" in some files
    ax.plot(traj[:, 0], traj[:, 1], lw=0.6, color="#94a3b8", zorder=1)
    # skeleton edges, when present
    edges = None
    sk = t.get(p["path"].rsplit("/", 1)[0] + "/Skeletons")
    if sk is not None:
        for k in t.keys(sk):
            e = sk[k].get("edges") if t.is_group(sk[k]) else None
            nodes = sk[k].get("nodes") if t.is_group(sk[k]) else None
            if e is not None and nodes is not None:
                nn = [str(_s(x)) for x in nodes[:]]
                if set(nn) <= set(names) or len(nn) == len(names):
                    edges = [(nn[int(u)], nn[int(v)]) for u, v in np.asarray(e[:])]
                    break
    pos = dict(zip(names, pts))
    if edges:
        for u, v in edges:
            if u in pos and v in pos and np.isfinite(pos[u]).all() and np.isfinite(pos[v]).all():
                ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=MUTED, lw=0.8, zorder=2)
    good = np.isfinite(pts).all(axis=1)
    cc = np.array(conf)
    sc = ax.scatter(pts[good, 0], pts[good, 1], c=np.where(np.isfinite(cc[good]), cc[good], 1.0), cmap="viridis",
                    vmin=0, vmax=1, s=22, zorder=3, edgecolors="white", linewidths=0.4)
    for nm, (x, y), ok in zip(names, pts, good):
        if ok:
            ax.annotate(nm, (x, y), fontsize=5.5, color=INK, xytext=(3, 3), textcoords="offset points")
    # zoom on the animal: the keypoints of this frame with a margin (the path is clipped to it)
    # The margin scales with the data: 60 % of the animal's extent in this frame, at least 5 % of the
    # span of the nearby path, so it works in pixels, cm or metres.
    if good.any():
        lo, hi = pts[good].min(axis=0), pts[good].max(axis=0)
        span = np.nanmax(traj, axis=0) - np.nanmin(traj, axis=0) if np.isfinite(traj).any() else hi - lo
        pad = max(0.6 * float((hi - lo).max()), 0.05 * float(np.nanmax(span)), 1e-9)
        ax.set_xlim(lo[0] - pad, hi[0] + pad)
        ax.set_ylim(lo[1] - pad, hi[1] + pad)
    if image_coords:
        ax.invert_yaxis()
    ax.set_aspect("equal", adjustable="box")
    u = unit or "unit not set"
    ax.set_xlabel(f"x ({u})", fontsize=8)
    ax.set_ylabel(f"y ({u})", fontsize=8)
    cb = fig.colorbar(sc, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("confidence", fontsize=7)
    cb.ax.tick_params(labelsize=6)
    ax.set_title(f"{title}: pose, frame {i}", fontsize=9, color=INK)
    fig.tight_layout()
    missing = int((~good).sum())
    cap = (f"Keypoints of {p['path']} ({p['n_keypoints']} keypoints, {n:,} frames) at frame {i}, coloured by "
           f"confidence, " + ("image coordinates (y down)" if image_coords else f"in {unit} (y up)") + "; grey: the path of '{names[0]}' over {b - a} frames around it"
           + (f"; {missing} keypoint(s) missing in this frame" if missing else "")
           + ". Check that the points sit on a plausible body shape (skeleton lines are not crossed), that "
           "confidence is high on visible body parts, and that the path is smooth rather than jumping.")
    return fig, cap


# --------------------------------------------------------------------------------------------- timeline
def timeline(t: Tree, s: dict, title: str):
    tabs = [x for x in (s.get("intervals") or []) if x.get("n_intervals")]
    if not tabs:
        return None
    tabs.sort(key=lambda x: (x["path"] != "/intervals/trials", x["path"]))
    tabs = tabs[:MAX_TABLES]
    fig, ax = _fig(7.2, 0.6 + 0.45 * len(tabs) + 0.8)
    labels = []
    tmin, tmax = np.inf, -np.inf
    for x in tabs:
        j = len(labels)  # row of this table (tables without valid times are skipped without a gap)
        g = t.get(x["path"])
        n = min(x["n_intervals"], MAX_INTERVALS)
        a = np.asarray(g.get("start_time")[:n], dtype=float)
        b = np.asarray(g.get("stop_time")[:n], dtype=float) if g.get("stop_time") is not None else a
        ok = np.isfinite(a) & np.isfinite(b)
        a, b = a[ok], b[ok]
        if not len(a):
            continue
        tmin, tmax = min(tmin, a.min()), max(tmax, b.max())
        ax.broken_barh(list(zip(a, np.maximum(b - a, 0))), (j - 0.35, 0.7), color=PALETTE[j % len(PALETTE)],
                       linewidth=0)
        # zero-length or very short intervals: draw a tick so they stay visible
        short = (b - a) < (b.max() - a.min()) / 2000 if len(a) > 1 else np.ones(len(a), bool)
        if short.any():
            ax.vlines(a[short], j - 0.35, j + 0.35, color=PALETTE[j % len(PALETTE)], lw=0.4)
        more = f" (first {n:,})" if x["n_intervals"] > n else ""
        labels.append(f"{x['path'].split('/')[-1]}  n={x['n_intervals']:,}{more}")
    if not labels:
        return None
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_ylim(-0.6, len(labels) - 0.4)
    ax.invert_yaxis()
    if s.get("t_start") is not None and s.get("t_stop") is not None:
        tmin, tmax = min(tmin, s["t_start"]), max(tmax, s["t_stop"])
    ax.set_xlim(tmin, tmax)
    ax.set_xlabel("time (s, session clock)", fontsize=8)
    ax.set_title(f"{title}: interval tables", fontsize=9, color=INK)
    fig.tight_layout()
    cap = ("Every interval table (trials, epochs, behavioural states, stimulus presentations) on the session "
           f"clock, over the span of all data in the file ({tmin:.0f}-{tmax:.0f} s). Look for tables that start "
           "or stop far from the rest of the data (a clock offset), gaps in the trials, and overlapping or "
           "negative intervals.")
    return fig, cap


PREVIEWS = [("raster", raster), ("traces", traces), ("pose", pose_frame), ("timeline", timeline)]
