"""
The synthetic fixture (tests/make_fixture.py) through the processor, without Docker: the clean file
passes, every planted problem is caught by the check that should catch it, outputs follow the
conventions, and nothing touches the network.
"""
from __future__ import annotations

import csv
import json
import os
import socket
from pathlib import Path

import pytest

from processor import main as app
from tests import make_fixture

HAS_ZARR = True
try:
    import hdmf_zarr  # noqa: F401
except ImportError:
    HAS_ZARR = False

PROV_KEYS = {"app", "version", "variant", "tools", "parameters", "inputs", "started", "finished", "wall_seconds",
             "peak_rss_mb", "gpu", "sessions", "citations"}


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("fixture")
    make_fixture.make(d, large=True, zarr=HAS_ZARR)
    return d


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def run(monkeypatch, tmp_path, in_dir, **params):
    out = tmp_path / "out"
    env = {"INPUT_DIR": str(in_dir), "OUTPUT_DIR": str(out), "TMPDIR": str(tmp_path / "tmp")}
    (tmp_path / "tmp").mkdir(exist_ok=True)
    for k in ("CHECKS", "INSPECTOR_CONFIG", "IMPORTANCE_THRESHOLD", "FAIL_ON", "PREVIEWS", "LABEL", "THREADS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {**env, **params}.items():
        monkeypatch.setenv(k, str(v))
    code = app.main()
    return code, out / "nwb-inspect"


@pytest.fixture(scope="module")
def default_run(fixture_dir, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    try:
        tmp = tmp_path_factory.mktemp("run")
        code, out = run(mp, tmp, fixture_dir)
    finally:
        mp.undo()
    rep = json.loads((out / "report.json").read_text())
    return code, out, {Path(f["file"]).name: f for f in rep["files"]}, rep


def checks_of(f):
    return {(m["check_group"], m["check_name"]) for m in f["messages"]}


def test_exit_and_outputs(default_run):
    code, out, files, rep = default_run
    assert code == 0  # FAIL_ON=none: problems are reported, the step succeeds
    for name in ("report.json", "report.pdf", "issues.csv", "summary.json", "provenance.json"):
        assert (out / name).is_file(), name
    assert (out / "report.pdf").read_bytes()[:4] == b"%PDF"
    assert len(files) == 6 + int(HAS_ZARR)
    prov = json.loads((out / "provenance.json").read_text())
    assert set(prov) == PROV_KEYS
    assert "10.7554/eLife.78362" in prov["citations"]
    summ = json.loads((out / "summary.json").read_text())
    assert summ["app"] == "nwb-inspect" and summ["n_files"] == len(files)
    assert all(Path(out / fig["path"]).is_file() and fig["caption"] for fig in summ["figures"])
    rows = list(csv.DictReader(open(out / "issues.csv")))
    assert len(rows) == sum(len(f["messages"]) for f in files.values())


def test_clean_file_passes(default_run):
    _, out, files, _ = default_run
    f = files["sub-M01_ses-S1_behavior+ecephys+ophys.nwb"]
    assert f["status"] == "pass", f["messages"]
    assert f["dandi_ready"] is True
    assert f["counts"]["CRITICAL"] == 0 and f["counts"]["BEST_PRACTICE_VIOLATION"] == 0
    s = f["summary"]
    assert s["units"]["n_units"] == 24
    assert s["units"]["labels"]["label"] == {"good": 16, "mua": 8}
    assert set(s["units"]["brain_areas"]) <= {"CA1", "DG"}
    assert s["trials"]["n_trials"] == 30
    assert s["subject"]["species"] == "Mus musculus"
    assert sum(p["n_rois"] for p in s["ophys"]["plane_segmentations"]) == 10
    assert len(s["ophys"]["imaging_planes"]) == 1  # the PlaneSegmentation's link is not counted twice
    assert s["pose"][0]["n_keypoints"] == 5 and s["pose"][0]["n_frames"] == 9000
    assert "ndx-pose" in s["extensions"]
    assert abs(s["duration_s"] - 300.0) < 1
    assert {Path(p["path"]).name.rsplit("_", 1)[-1] for p in f["previews"]} == \
        {"raster.png", "traces.png", "pose.png", "timeline.png"}
    for p in f["previews"]:
        assert (out / p["path"]).stat().st_size > 5000


def test_missing_species_is_critical_and_blocks_dandi(default_run):
    f = default_run[2]["sub-M02_ses-S1_ecephys.nwb"]
    assert ("inspector", "check_subject_species_exists") in checks_of(f)
    assert f["status"] == "fail"
    assert f["dandi_ready"] is False


def test_missing_unit_is_a_violation(default_run):
    f = default_run[2]["sub-M03_ses-S1_behavior.nwb"]
    assert ("inspector", "check_missing_unit") in checks_of(f)
    assert f["status"] == "warn"


def test_timestamps_out_of_order(default_run):
    f = default_run[2]["sub-M04_ses-S1_behavior.nwb"]
    assert ("inspector", "check_timestamps_ascending") in checks_of(f)
    assert f["status"] == "warn"


def test_schema_error(default_run):
    f = default_run[2]["sub-M05_ses-S1_behavior.nwb"]
    assert ("schema", "DtypeError") in checks_of(f)
    assert f["status"] == "fail" and f["dandi_ready"] is False


def test_uncompressed_large_dataset(default_run):
    f = default_run[2]["sub-M06_ses-S1_ecephys.nwb"]
    assert ("inspector", "check_small_dataset_compression") in checks_of(f)
    big = f["summary"]["largest_datasets"][0]
    assert big["path"] == "/acquisition/ElectricalSeries/data"
    assert big["flag_uncompressed_large"] is True and big["compression"] is None


@pytest.mark.skipif(not HAS_ZARR, reason="hdmf-zarr not installed")
def test_zarr_nwb(default_run):
    f = default_run[2]["sub-M01_ses-S1_behavior+ecephys+ophys.nwb.zarr"]
    assert f["format"] == "zarr"
    assert f["status"] == "pass", f["messages"]
    assert f["summary"]["units"]["n_units"] == 24
    assert len(f["previews"]) == 4


def test_fail_on_critical(fixture_dir, tmp_path, monkeypatch):
    code, out = run(monkeypatch, tmp_path, fixture_dir, FAIL_ON="critical", PREVIEWS="false",
                    CHECKS="inspector")
    assert code == 1
    assert (out / "report.json").is_file()  # the report is written before failing


def test_threshold_and_default_config(fixture_dir, tmp_path, monkeypatch):
    code, out = run(monkeypatch, tmp_path, fixture_dir, IMPORTANCE_THRESHOLD="CRITICAL", INSPECTOR_CONFIG="default",
                    PREVIEWS="false", LABEL="final")
    assert code == 0
    out = out / "final"
    rep = json.loads((out / "report.json").read_text())
    files = {Path(f["file"]).name: f for f in rep["files"]}
    assert all(m["importance"] in ("CRITICAL", "ERROR") for f in files.values() for m in f["messages"])
    # with the default configuration species is not critical for the inspector, but the dandi step still is
    f = files["sub-M02_ses-S1_ecephys.nwb"]
    assert ("dandi", "check_subject_species_exists") in checks_of(f)
    assert f["dandi_ready"] is False


def test_flat_layout_and_symlinks(fixture_dir, tmp_path, monkeypatch):
    flat = tmp_path / "flat"
    flat.mkdir()
    os.symlink(fixture_dir / "nwb" / "sub-M03_ses-S1_behavior.nwb", flat / "sub-M03_ses-S1_behavior.nwb")
    (flat / "notes.txt").write_text("not NWB")
    (flat / "broken.nwb").write_text("not HDF5")
    code, out = run(monkeypatch, tmp_path, flat, PREVIEWS="false")
    assert code == 0
    rep = json.loads((out / "report.json").read_text())
    assert [f["file_id"] for f in rep["files"]] == ["sub-M03_ses-S1"]


def test_bad_parameters_and_no_input(tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    assert run(monkeypatch, tmp_path, tmp_path / "empty", CHECKS="schema,typo")[0] == 2
    assert run(monkeypatch, tmp_path, tmp_path / "empty", FAIL_ON="always")[0] == 2
    assert run(monkeypatch, tmp_path, tmp_path / "empty")[0] == 1
