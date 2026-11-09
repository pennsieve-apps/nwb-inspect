# Sample input

`nwb-inspect` takes any NWB file: put one or more `.nwb` files (or NWB-Zarr `*.nwb.zarr` folders) in
the `nwb` input. Folders are searched recursively.

- **Synthetic, with planted problems:** `review/` (committed, 3 MB) holds the files
  `tests/make_fixture.py` writes: one clean file and four with one problem each (missing species,
  a time series without unit, timestamps going backwards, a schema error). The review run of a
  release uses them. `python -m tests.make_fixture <dir> --large --zarr` also writes a 64 MB
  uncompressed file and the clean file as NWB-Zarr.
- **Any DANDI asset:** e.g. `dandi download "https://dandiarchive.org/dandiset/000044/draft"`
  (Grosmark & Buzsáki, CA1 units on a linear track, 5 GB per file), or the IBL Brain Wide Map's
  processed files (DANDI:000409, ~0.5 GB each). Upload them to a Pennsieve dataset and link them to
  the `nwb` port.
- **Outputs of the other apps:** link `ephys-curate`'s `units`, `ophys-traces`' `traces`,
  `pose-estimate`'s `pose`, `pose-kinematics`' `kinematics` or `behavior-syllables`' outputs to the
  `nwb` port; nwb-inspect picks out the `.nwb` files and ignores the rest.
