"""
report.pdf with Matplotlib's PDF backend (fonts: DejaVu Sans, shipped inside Matplotlib, so nothing
is fetched or installed and it runs on Lambda): a cover page with every file and its status, then per
file one page with the summary and the issues, and one page with the previews.
"""
from __future__ import annotations

import textwrap

from .summary import describe_age

A4 = (8.27, 11.69)
M = 0.55  # margin, inches
INK = "#111827"
MUTED = "#6b7280"
RULE = "#e5e7eb"
STATUS_COLOUR = {"pass": "#15803d", "warn": "#b45309", "fail": "#b91c1c"}
IMP_SHORT = {"CRITICAL": "critical", "BEST_PRACTICE_VIOLATION": "violation",
             "BEST_PRACTICE_SUGGESTION": "suggestion", "ERROR": "check error"}
IMP_COLOUR = {"CRITICAL": "#b91c1c", "BEST_PRACTICE_VIOLATION": "#b45309", "BEST_PRACTICE_SUGGESTION": "#4b5563",
              "ERROR": "#7c3aed"}


def _wrap(text, width, max_lines=None):
    lines = []
    for para in str(text).split("\n"):
        lines.extend(textwrap.wrap(para, width=width, break_long_words=True, break_on_hyphens=False) or [""])
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(0, width - 1)].rstrip() + "…"
    return lines


class Page:
    """One A4 page with a text cursor measured in inches from the top."""

    def __init__(self, pdf, footer: str):
        import matplotlib.pyplot as plt

        self.plt = plt
        self.pdf = pdf
        self.fig = plt.figure(figsize=A4)
        self.y = M
        self.footer = footer

    def _xy(self, x, y):
        return x / A4[0], 1 - y / A4[1]

    def text(self, x, s, size=8, color=INK, weight="normal", family="DejaVu Sans", dy=None, **kw):
        self.fig.text(*self._xy(x, self.y), s, fontsize=size, color=color, weight=weight, family=family, va="top",
                      **kw)
        if dy is not None:
            self.y += dy

    def line(self, x0=M, x1=A4[0] - M, color=RULE, lw=0.6):
        self.fig.add_artist(self.plt.Line2D([x0 / A4[0], x1 / A4[0]], [1 - self.y / A4[1]] * 2, color=color, lw=lw))

    def badge(self, x, label, colour, size=8):
        self.fig.text(*self._xy(x, self.y), f" {label.upper()} ", fontsize=size, color="white", weight="bold",
                      va="top", bbox=dict(boxstyle="round,pad=0.25", fc=colour, ec="none"))

    def room(self, h):
        return self.y + h <= A4[1] - M - 0.3

    def close(self, page_no):
        self.fig.text(*self._xy(M, A4[1] - M + 0.1), self.footer, fontsize=6, color=MUTED, va="top")
        self.fig.text(*self._xy(A4[0] - M, A4[1] - M + 0.1), str(page_no), fontsize=6, color=MUTED, va="top",
                      ha="right")
        self.pdf.savefig(self.fig)
        self.plt.close(self.fig)


def _fmt_size(b):
    if not b:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1000:
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1000
    return f"{b:.1f} PB"


def _fmt_dur(s):
    if s is None:
        return "-"
    s = float(s)
    if s < 120:
        return f"{s:.1f} s"
    if s < 7200:
        return f"{s / 60:.1f} min"
    return f"{s / 3600:.2f} h"


def _shape(x):
    return "×".join(str(v) for v in x) if x else "-"


def _summary_lines(f: dict) -> list[tuple[str, str]]:
    s = f.get("summary") or {}
    rows = []
    rows.append(("NWB version", str(s.get("nwb_version") or "-")))
    rows.append(("Identifier", str(s.get("identifier") or "-")))
    rows.append(("Session start", str(s.get("session_start_time") or "-")))
    gen = s.get("general") or {}
    if gen.get("session_id"):
        rows.append(("Session id", str(gen["session_id"])))
    rows.append(("Data span", f"{_fmt_dur(s.get('duration_s'))}"
                 + (f" ({s['t_start']:.1f}-{s['t_stop']:.1f} s)" if s.get("t_start") is not None else "")))
    if s.get("session_description"):
        rows.append(("Description", str(s["session_description"])))
    for k in ("lab", "institution"):
        if gen.get(k):
            rows.append((k.capitalize(), str(gen[k])))
    sub = s.get("subject")
    if sub:
        age = describe_age(s)
        bits = [f"id {sub.get('subject_id', '—')}", str(sub.get("species", "species missing")),
                f"sex {sub.get('sex', '—')}", f"age {age or '—'}"]
        for k in ("genotype", "strain"):
            if sub.get(k):
                bits.append(f"{k} {sub[k]}")
        rows.append(("Subject", ", ".join(bits)))
    else:
        rows.append(("Subject", "none"))
    if s.get("devices"):
        rows.append(("Devices", ", ".join(d["name"] + (f" ({d['description'][:60]})" if d.get("description") else "")
                                          for d in s["devices"][:6])))
    if s.get("electrode_groups"):
        eg = s["electrode_groups"]
        rows.append(("Electrode groups", f"{len(eg)}: " + ", ".join(
            f"{g['name']}" + (f" [{g['location']}]" if g.get("location") else "") for g in eg[:8])
            + (" …" if len(eg) > 8 else "")))
    if s.get("electrodes"):
        rows.append(("Electrodes", f"{s['electrodes']['n_rows']} rows"))
    u = s.get("units")
    if u:
        lab = "; ".join(f"{k}: " + ", ".join(f"{a} {b}" for a, b in v.items()) for k, v in (u.get("labels") or {}).items()
                        if v)
        areas = ", ".join(f"{a} ({b})" for a, b in list((u.get("brain_areas") or {}).items())[:10])
        rows.append(("Units", f"{u['n_units']} units, {u['n_spikes']:,} spikes" + (f"; {lab}" if lab else "")))
        if areas:
            rows.append(("Unit brain areas", areas))
    oph = s.get("ophys") or {}
    if oph.get("imaging_planes") or oph.get("plane_segmentations"):
        planes = ", ".join(f"{p['path'].split('/')[-1]} ({p.get('location') or '?'}, {p.get('indicator') or '?'})"
                           for p in oph.get("imaging_planes", []))
        rois = ", ".join(f"{p['path'].split('/')[-1]}: {p['n_rois']} ROIs" for p in oph.get("plane_segmentations", []))
        rows.append(("Ophys", "; ".join(x for x in (planes, rois) if x)))
        rrs = ", ".join(f"{x['path'].split('/')[-1]} {_shape(x['shape'])}"
                        + (f" @ {x['rate_hz']:.2f} Hz" if x.get("rate_hz") else "")
                        for x in oph.get("roi_response_series", [])[:6])
        if rrs:
            rows.append(("ROI series", rrs))
    for p in s.get("pose") or []:
        rows.append(("Pose", f"{p['path']}: {p['n_keypoints']} keypoints, {p['n_frames'] or 0:,} frames"
                     + (f" @ {p['rate_hz']:.1f} Hz" if p.get("rate_hz") else "")
                     + (f", {p['source_software']}" if p.get("source_software") else "")))
    if s.get("intervals"):
        rows.append(("Intervals", ", ".join(f"{x['path'].split('/')[-1]} ({x['n_intervals']:,}; "
                                            f"{len(x['columns'])} columns)" for x in s["intervals"][:8])))
    ts = [x for x in s.get("time_series") or [] if x["type"] not in ("RoiResponseSeries",)]
    if ts:
        rows.append(("Time series", f"{len(ts)}: " + "; ".join(
            f"{x['path'].split('/')[-1]} [{x['type']}] {_shape(x['shape'])}"
            + (f" @ {x['rate_hz']:.4g} Hz" if x.get("rate_hz") else "") for x in ts[:10])
            + (" …" if len(ts) > 10 else "")))
    if s.get("extensions"):
        rows.append(("Extensions", ", ".join(f"{k} {'/'.join(v)}" for k, v in s["extensions"].items())))
    rows.append(("File size", _fmt_size(s.get("file_size_bytes")) + f" ({s.get('format', 'hdf5').upper()})"))
    big = s.get("largest_datasets") or []
    if big:
        rows.append(("Largest datasets", "; ".join(
            f"{d['path']} {_fmt_size(d['nbytes'])}"
            + (f" {d['compression']}" + (f"({d['compression_opts']})" if d.get("compression_opts") is not None else "")
               + (f" ×{d['compression_ratio']}" if d.get("compression_ratio") else "") if d.get("compression")
               else " UNCOMPRESSED")
            + (f" chunks {_shape(d['chunks'])}" if d.get("chunks") else " contiguous")
            for d in big[:4])))
    return rows


def _groups(messages):
    groups = {}
    order = {"CRITICAL": 0, "ERROR": 1, "BEST_PRACTICE_VIOLATION": 2, "BEST_PRACTICE_SUGGESTION": 3}
    for m in messages:
        key = (m["importance"], m["check_group"], m["check_name"])
        g = groups.setdefault(key, {"importance": m["importance"], "group": m["check_group"],
                                    "check": m["check_name"], "count": 0, "example": m, "blocking": False})
        g["count"] += 1
        g["blocking"] = g["blocking"] or bool(m.get("dandi_blocking"))
    return sorted(groups.values(), key=lambda g: (order.get(g["importance"], 9), -g["count"], g["check"]))


def write_pdf(path, report: dict, figures: dict):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    from matplotlib.backends.backend_pdf import PdfPages

    files = report["files"]
    footer = (f"nwb-inspect {report['version']} · NWB Inspector {report['tools'].get('nwbinspector')} · "
              f"PyNWB {report['tools'].get('pynwb')} · dandi {report['tools'].get('dandi')} · {report['generated'][:16]} UTC")
    page_no = 0
    with PdfPages(path, metadata={"Title": "NWB inspection report", "Creator": "Pennsieve nwb-inspect"}) as pdf:
        # ---------------------------------------------------------------- cover
        pg = Page(pdf, footer)
        pg.text(M, "NWB inspection report", size=18, weight="bold", dy=0.42)
        n = {k: sum(1 for f in files if f["status"] == k) for k in ("pass", "warn", "fail")}
        ready = sum(1 for f in files if f.get("dandi_ready"))
        pg.text(M, f"{len(files)} file(s): {n['pass']} pass, {n['warn']} warn, {n['fail']} fail. "
                   f"{ready} of {len(files)} ready for DANDI upload.", size=10, dy=0.28)
        p = report["parameters"]
        pg.text(M, f"Checks: {p['CHECKS']} · NWB Inspector configuration: {p['INSPECTOR_CONFIG']} · "
                   f"threshold: {p['IMPORTANCE_THRESHOLD']} · FAIL_ON={p['FAIL_ON']}", size=7.5, color=MUTED, dy=0.22)
        for line in _wrap(
                "pass: no critical problem and no best-practice violation. warn: best-practice violations (the file "
                "is valid NWB but should be fixed before sharing). fail: the file breaks the NWB schema, or has a "
                "problem NWB Inspector or DANDI rate as critical (e.g. no subject species, sex or age). DANDI-ready: "
                "what `dandi validate` (which `dandi upload` runs first) would accept: no schema error, no NWB "
                "Inspector CRITICAL or check error under its DANDI configuration, and metadata DANDI can read. "
                "The file name may still need `dandi organize`, which renames files automatically.", 120):
            pg.text(M, line, size=7, color=MUTED, dy=0.15)
        pg.y += 0.15
        cols = [(M, "#"), (M + 0.3, "file"), (M + 4.35, "size"), (M + 5.0, "status"), (M + 5.65, "crit."),
                (M + 6.1, "viol."), (M + 6.55, "sugg."), (M + 7.0, "DANDI")]

        def header(pg):
            for x, h in cols:
                pg.text(x, h, size=7, color=MUTED, weight="bold")
            pg.y += 0.18
            pg.line()
            pg.y += 0.06

        header(pg)
        for i, f in enumerate(files, 1):
            if not pg.room(0.22):
                page_no += 1
                pg.close(page_no)
                pg = Page(pdf, footer)
                header(pg)
            c = f["counts"]
            name = f["file"]
            if len(name) > 66:
                name = "…" + name[-65:]
            pg.text(cols[0][0], str(i), size=7)
            pg.text(cols[1][0], name, size=6.5)
            pg.text(cols[2][0], _fmt_size(f.get("size_bytes")), size=7)
            pg.badge(cols[3][0], f["status"], STATUS_COLOUR[f["status"]], size=6)
            pg.text(cols[4][0], str(c.get("CRITICAL", 0)), size=7, color=IMP_COLOUR["CRITICAL"] if c.get("CRITICAL") else INK)
            pg.text(cols[5][0], str(c.get("BEST_PRACTICE_VIOLATION", 0)), size=7)
            pg.text(cols[6][0], str(c.get("BEST_PRACTICE_SUGGESTION", 0)), size=7)
            pg.text(cols[7][0], "yes" if f.get("dandi_ready") else "no", size=7)
            pg.y += 0.22
        page_no += 1
        pg.close(page_no)

        # ---------------------------------------------------------------- one or two pages per file
        for i, f in enumerate(files, 1):
            pg = Page(pdf, footer)
            pg.badge(M, f["status"], STATUS_COLOUR[f["status"]], size=9)
            title = f["file_id"] if len(f["file_id"]) <= 60 else f["file_id"][:59] + "…"
            pg.text(M + 0.75, f"{i}. {title}", size=12, weight="bold", dy=0.3)
            for line in _wrap(f["file"], 130, 2):
                pg.text(M, line, size=6.5, color=MUTED, dy=0.13)
            c = f["counts"]
            status_line = (f"{c.get('CRITICAL', 0)} critical · {c.get('BEST_PRACTICE_VIOLATION', 0)} best-practice "
                           f"violations · {c.get('BEST_PRACTICE_SUGGESTION', 0)} suggestions"
                           + (f" · {c['ERROR']} checks could not run" if c.get("ERROR") else "")
                           + f" · DANDI-ready: {'yes' if f.get('dandi_ready') else 'no'}"
                           + (f" · dandi organize path: {f['dandi']['suggested_path']}"
                              if (f.get("dandi") or {}).get("suggested_path") else ""))
            for line in _wrap(status_line, 125, 3):
                pg.text(M, line, size=7.5, dy=0.16)
            pg.y += 0.06
            if f.get("error"):
                for line in _wrap(f"Could not read: {f['error']}", 120, 4):
                    pg.text(M, line, size=8, color=STATUS_COLOUR["fail"], dy=0.16)
            pg.line()
            pg.y += 0.1
            pg.text(M, "Contents", size=9.5, weight="bold", dy=0.2)
            for k, v in _summary_lines(f):
                lines = _wrap(v, 112, 4)
                if not pg.room(0.14 * len(lines) + 0.02):
                    break
                pg.text(M, k, size=7, color=MUTED, weight="bold")
                for line in lines:
                    pg.text(M + 1.35, line, size=7, dy=0.14)
                pg.y += 0.03
            pg.y += 0.1
            pg.line()
            pg.y += 0.1
            groups = _groups(f["messages"])
            pg.text(M, f"Issues ({len(f['messages'])} messages in {len(groups)} groups)", size=9.5, weight="bold",
                    dy=0.22)
            if not groups:
                pg.text(M, "No issues at or above the threshold.", size=7.5, color=MUTED, dy=0.18)
            shown = 0
            for g in groups:
                ex = g["example"]
                where = ex.get("location") or ""
                if ex.get("object_name") and ex["object_name"] not in where:
                    where = (where + " " if where else "") + f"({ex.get('object_type') or ''} {ex['object_name']})".replace("( ", "(")
                msg = ex["message"]
                lines = _wrap(msg, 98, 2)
                h = 0.14 + 0.125 * len(lines) + 0.05
                if not pg.room(h + 0.2):
                    break
                pg.text(M, IMP_SHORT.get(g["importance"], g["importance"]), size=6.5, weight="bold",
                        color=IMP_COLOUR.get(g["importance"], INK))
                pg.text(M + 0.75, f"{g['check']}", size=7, weight="bold")
                meta = f"{g['group']} · ×{g['count']}" + (" · blocks DANDI" if g.get("blocking") else "")
                if where:
                    room = 64 - len(meta) - 9
                    w = where if len(where) <= room else "…" + where[-(room - 1):]
                    meta += f" · e.g. {w}"
                pg.text(M + 3.9, meta, size=6.5, color=MUTED, dy=0.14)
                for line in lines:
                    pg.text(M + 0.75, line, size=6.5, dy=0.125)
                pg.y += 0.05
                shown += 1
            if shown < len(groups):
                pg.text(M, f"… {len(groups) - shown} more groups; every message is in issues.csv and report.json.",
                        size=7, color=MUTED, dy=0.16)
            page_no += 1
            pg.close(page_no)

            figs = figures.get(f["file_id"]) or []
            if figs:
                pg = Page(pdf, footer)
                title = f["file_id"] if len(f["file_id"]) <= 60 else f["file_id"][:59] + "…"
                pg.text(M, f"{i}. {title}: previews", size=12, weight="bold", dy=0.3)
                pg.text(M, "Small slices read from the file to show what is in it; captions say what to look for.",
                        size=7, color=MUTED, dy=0.2)
                fig = pg.fig
                cell_w = (A4[0] - 2 * M - 0.3) / 2
                y = pg.y
                for r0 in range(0, min(len(figs), 4), 2):
                    row_h = 0.0
                    for col, (png, cap) in enumerate(figs[r0:r0 + 2]):
                        x = M + col * (cell_w + 0.3)
                        img = mpimg.imread(png)
                        h_img = min(3.4, cell_w * img.shape[0] / img.shape[1])
                        w_img = h_img * img.shape[1] / img.shape[0]
                        ax = fig.add_axes([x / A4[0], 1 - (y + h_img) / A4[1], w_img / A4[0], h_img / A4[1]])
                        ax.imshow(img)
                        ax.axis("off")
                        lines = _wrap(cap, 72, 12)
                        for j, line in enumerate(lines):
                            fig.text(x / A4[0], 1 - (y + h_img + 0.1 + 0.12 * j) / A4[1], line, fontsize=6,
                                     color=INK, va="top")
                        row_h = max(row_h, h_img + 0.1 + 0.12 * len(lines))
                    y += row_h + 0.35
                page_no += 1
                pg.close(page_no)
