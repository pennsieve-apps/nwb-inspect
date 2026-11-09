"""
Small synthetic NWB files for the tests and the review run: one clean file and files with one planted
problem each, so the tests can assert that each problem is caught and the clean file passes.

  sub-M01_ses-S1_behavior+ecephys+ophys.nwb  clean: subject, units, electrodes, trials, position,
                                              ΔF/F of 10 ROIs, pose (when ndx-pose is installed)
  sub-M02_ses-S1_ecephys.nwb                 subject without species        (CRITICAL, DANDI blocks)
  sub-M03_ses-S1_behavior.nwb                a TimeSeries with an empty unit (best-practice violation)
  sub-M04_ses-S1_behavior.nwb                timestamps going backwards      (best-practice violation)
  sub-M05_ses-S1_behavior.nwb                schema error: starting_time.rate written as text
  sub-M06_ses-S1_ecephys.nwb (--large)       a 64 MB uncompressed dataset     (NWB Inspector suggestion)
  sub-M07_ses-S1_behavior+image.nwb          an ImageSeries whose external video is missing: CRITICAL for NWB
                                              Inspector but not one of the DANDI configuration's subject checks;
                                              `dandi validate` refuses it all the same
  sub-M08_ses-S1_behavior+ecephys.nwb        shares its identifier with M07 (check_unique_identifiers), regular
                                              timestamps stored explicitly, one negative spike time
  sub-M01_ses-S1_behavior+ecephys+ophys.nwb.zarr (--zarr)  the clean file as NWB-Zarr

Usage: python -m tests.make_fixture OUT_DIR [--large] [--zarr]   (files go to OUT_DIR/nwb/)
Needs pynwb (and ndx-pose for the pose part, hdmf-zarr for --zarr).
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np

START = dt.datetime(2026, 3, 2, 10, 30, tzinfo=dt.timezone.utc)
DURATION = 300.0


def _nwb(session_id, subject_kw, identifier=None, **kw):
    from pynwb import NWBFile
    from pynwb.file import Subject

    subj = Subject(**subject_kw) if subject_kw is not None else None
    return NWBFile(
        session_description="Synthetic session for nwb-inspect tests",
        identifier=identifier or f"nwb-inspect-fixture-{(subject_kw or {}).get('subject_id', 'x')}-{session_id}",
        session_start_time=START,
        session_id=session_id,
        experimenter=["Doe, Jane"],
        lab="Test lab",
        institution="University of Pennsylvania",
        experiment_description="Synthetic data with planted problems for testing nwb-inspect.",
        keywords=["test", "synthetic"],
        subject=subj,
        **kw,
    )


def _subject(sid, species=True):
    kw = dict(subject_id=sid, sex="F", age="P90D", description="synthetic mouse", strain="C57BL/6J")
    if species:
        kw["species"] = "Mus musculus"
    return kw


def _compressed(data, chunks=None):
    from hdmf.backends.hdf5.h5_utils import H5DataIO

    return H5DataIO(data=data, compression="gzip", compression_opts=4, chunks=chunks or True)


def _ecephys(nwb, rng, n_units=24):
    dev = nwb.create_device(name="Probe0", description="synthetic 32-channel probe", manufacturer="Test")
    grp = nwb.create_electrode_group(name="shank0", description="shank 0", location="CA1", device=dev)
    for i in range(32):
        nwb.add_electrode(group=grp, location="CA1" if i < 16 else "DG", x=0.0, y=20.0 * i, z=0.0, rel_x=0.0,
                          rel_y=20.0 * i)
    from pynwb.misc import Units

    nwb.units = Units(name="units", description="synthetic sorted units", resolution=1 / 30000.0)
    nwb.add_unit_column(name="label", description="curation label: good / mua")
    nwb.add_unit_column(name="depth", description="depth along the probe (um)")
    for u in range(n_units):
        rate = rng.uniform(1, 15)
        n = rng.poisson(rate * DURATION)
        st = np.sort(rng.uniform(0, DURATION, n))
        ch = int(rng.integers(0, 32))
        nwb.add_unit(spike_times=st, electrodes=[ch], label="good" if u % 3 else "mua", depth=20.0 * ch,
                     obs_intervals=[[0.0, DURATION]])


def _trials(nwb, rng, n=30):
    nwb.add_trial_column(name="stimulus", description="stimulus condition")
    t = 5.0
    for i in range(n):
        nwb.add_trial(start_time=t, stop_time=t + 4.0, stimulus=["left", "right"][i % 2])
        t += float(rng.uniform(8, 10))


def _position(nwb, rng, n=15000, rate=50.0, unit="meters", timestamps=None):
    from pynwb.behavior import Position, SpatialSeries

    beh = nwb.create_processing_module(name="behavior", description="behaviour")
    xy = np.cumsum(rng.normal(0, 0.002, (n, 2)), axis=0).astype("float32")
    kw = dict(timestamps=timestamps) if timestamps is not None else dict(rate=rate, starting_time=0.0)
    ss = SpatialSeries(name="position", description="animal position", data=_compressed(xy), unit=unit,
                       reference_frame="arena corner", **kw)
    beh.add(Position(spatial_series=ss))
    return beh


def _ophys(nwb, rng, n_rois=10, n_t=3000, rate=10.0):
    from pynwb.ophys import DfOverF, ImageSegmentation, OpticalChannel, RoiResponseSeries

    dev = nwb.create_device(name="Microscope", description="two-photon microscope", manufacturer="Test")
    ch = OpticalChannel(name="green", description="green channel", emission_lambda=520.0)
    plane = nwb.create_imaging_plane(name="ImagingPlane", optical_channel=ch, imaging_rate=rate,
                                     description="layer 2/3", device=dev, excitation_lambda=920.0,
                                     indicator="GCaMP6f", location="VISp")
    oph = nwb.create_processing_module(name="ophys", description="optical physiology")
    seg = ImageSegmentation()
    ps = seg.create_plane_segmentation(name="PlaneSegmentation", description="ROIs", imaging_plane=plane)
    for i in range(n_rois):
        m = np.zeros((32, 32), dtype="float32")
        r, c = 3 + 2 * i, 3 + (i * 7) % 24
        m[r:r + 3, c:c + 3] = 1
        ps.add_roi(image_mask=m)
    oph.add(seg)
    region = ps.create_roi_table_region(region=list(range(n_rois)), description="all ROIs")
    t = np.arange(n_t) / rate
    dff = rng.normal(0, 0.05, (n_t, n_rois))
    for j in range(n_rois):
        for ev in rng.uniform(0, n_t / rate, 12):
            k = t >= ev
            dff[k, j] += 0.8 * np.exp(-(t[k] - ev) / 0.7)
    rrs = RoiResponseSeries(name="RoiResponseSeries", data=_compressed(dff.astype("float32")), rois=region,
                            unit="n.a.", rate=rate, starting_time=0.0, description="ΔF/F")
    oph.add(DfOverF(roi_response_series=rrs))


def _pose(nwb, beh, rng, n=9000, rate=30.0):
    try:
        from ndx_pose import PoseEstimation, PoseEstimationSeries, Skeleton, Skeletons
    except ImportError:
        return False
    names = ["nose", "left_ear", "right_ear", "body_center", "tail_base"]
    offs = np.array([[0, -20], [-8, -12], [8, -12], [0, 0], [0, 20]], dtype=float)
    centre = 200 + np.cumsum(rng.normal(0, 1.0, (n, 2)), axis=0)
    cam = nwb.create_device(name="Camera", description="top-view camera", manufacturer="Test")
    skel = Skeleton(name="mouse", nodes=names, edges=np.array([[0, 1], [0, 2], [1, 3], [2, 3], [3, 4]], dtype="uint8"))
    series = []
    for k, nm in enumerate(names):
        xy = centre + offs[k] + rng.normal(0, 0.5, (n, 2))
        series.append(PoseEstimationSeries(name=nm, description=f"{nm} position", data=_compressed(xy),
                                           unit="pixels", reference_frame="(0,0) is the top-left corner",
                                           confidence=rng.uniform(0.8, 1.0, n), rate=rate, starting_time=0.0))
    pe = PoseEstimation(name="PoseEstimation", pose_estimation_series=series, description="synthetic pose",
                        source_software="DeepLabCut", scorer="synthetic", skeleton=skel, devices=[cam])
    beh.add(Skeletons(skeletons=[skel]))
    beh.add(pe)
    return True


def _write(nwb, path: Path):
    from pynwb import NWBHDF5IO

    path.parent.mkdir(parents=True, exist_ok=True)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)


def clean(path: Path, rng):
    nwb = _nwb("S1", _subject("M01"))
    _ecephys(nwb, rng)
    _trials(nwb, rng)
    beh = _position(nwb, rng)
    _ophys(nwb, rng)
    _pose(nwb, beh, rng)
    _write(nwb, path)


def no_species(path: Path, rng):
    nwb = _nwb("S1", _subject("M02", species=False))
    _ecephys(nwb, rng, n_units=6)
    _write(nwb, path)


def no_unit(path: Path, rng):
    from pynwb import TimeSeries

    nwb = _nwb("S1", _subject("M03"))
    beh = nwb.create_processing_module(name="behavior", description="behaviour")
    beh.add(TimeSeries(name="running_speed", description="running speed", data=_compressed(rng.random(5000)),
                       unit="", rate=50.0, starting_time=0.0))
    _write(nwb, path)


def bad_timestamps(path: Path, rng):
    ts = np.arange(5000) / 50.0
    ts[100:110] = ts[100:110][::-1]  # ten samples go backwards (inside the first 200)
    nwb = _nwb("S1", _subject("M04"))
    _position(nwb, rng, n=5000, timestamps=ts)
    _write(nwb, path)


def schema_error(path: Path, rng):
    import h5py

    nwb = _nwb("S1", _subject("M05"))
    _position(nwb, rng, n=2000)
    _write(nwb, path)
    with h5py.File(str(path), "a") as f:
        # starting_time.rate must be a float; make it text
        f["processing/behavior/Position/position/starting_time"].attrs["rate"] = "fifty"


def large_uncompressed(path: Path, rng):
    from pynwb.ecephys import ElectricalSeries

    nwb = _nwb("S1", _subject("M06"))
    dev = nwb.create_device(name="Probe0", description="probe")
    grp = nwb.create_electrode_group(name="shank0", description="shank", location="CA1", device=dev)
    for _ in range(64):
        nwb.add_electrode(group=grp, location="CA1")
    region = nwb.create_electrode_table_region(region=list(range(64)), description="all")
    data = rng.integers(-500, 500, size=(500_000, 64), dtype=np.int16)  # 64 MB, written contiguous
    nwb.add_acquisition(ElectricalSeries(name="ElectricalSeries", data=data, electrodes=region, rate=30000.0,
                                         starting_time=0.0, conversion=1e-6))
    _write(nwb, path)


SHARED_ID = "nwb-inspect-fixture-shared-identifier"


def missing_external_video(path: Path, rng):
    from pynwb.image import ImageSeries

    nwb = _nwb("S1", _subject("M07"), identifier=SHARED_ID)
    nwb.add_acquisition(ImageSeries(name="BehaviorVideo", description="top camera", unit="n.a.",
                                    external_file=["sub-M07_ses-S1_behavior+image/video_missing.mp4"],
                                    starting_frame=[0], format="external", rate=30.0, starting_time=0.0,
                                    num_samples=900))
    _write(nwb, path)


def shared_identifier(path: Path, rng):
    from pynwb.misc import Units

    nwb = _nwb("S1", _subject("M08"), identifier=SHARED_ID)
    _position(nwb, rng, n=3000, timestamps=np.arange(3000) / 50.0)  # regular: rate would do
    nwb.units = Units(name="units", description="units", resolution=1 / 30000.0)
    nwb.add_unit(spike_times=np.array([-0.5, 1.0, 2.0, 3.0]))
    nwb.add_unit(spike_times=np.array([0.5, 1.5]))
    _write(nwb, path)


FILES = {
    "sub-M01_ses-S1_behavior+ecephys+ophys.nwb": clean,
    "sub-M02_ses-S1_ecephys.nwb": no_species,
    "sub-M03_ses-S1_behavior.nwb": no_unit,
    "sub-M04_ses-S1_behavior.nwb": bad_timestamps,
    "sub-M05_ses-S1_behavior.nwb": schema_error,
    "sub-M07_ses-S1_behavior+image.nwb": missing_external_video,
    "sub-M08_ses-S1_behavior+ecephys.nwb": shared_identifier,
}


def make(out: Path, large=False, zarr=False, seed=0) -> Path:
    d = Path(out) / "nwb"
    d.mkdir(parents=True, exist_ok=True)
    for name, fn in FILES.items():
        fn(d / name, np.random.default_rng(seed))
    if large:
        large_uncompressed(d / "sub-M06_ses-S1_ecephys.nwb", np.random.default_rng(seed))
    if zarr:
        from hdmf_zarr.nwb import NWBZarrIO
        from pynwb import NWBHDF5IO

        src = d / "sub-M01_ses-S1_behavior+ecephys+ophys.nwb"
        with NWBHDF5IO(str(src), "r") as read_io, NWBZarrIO(str(src) + ".zarr", mode="w") as zio:
            zio.export(src_io=read_io, write_args=dict(link_data=False))
        # a copy is a new file and needs its own identifier (check_unique_identifiers)
        import zarr

        zarr.open_group(str(src) + ".zarr", mode="r+")["identifier"][...] = "nwb-inspect-fixture-M01-S1-zarr"
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--large", action="store_true", help="also the 64 MB uncompressed file")
    ap.add_argument("--zarr", action="store_true", help="also the clean file as NWB-Zarr")
    a = ap.parse_args()
    print(make(Path(a.out), a.large, a.zarr))
