# nwb-inspect

This app is built on the **Neurodata Without Borders (NWB)** tools: **[PyNWB](https://github.com/NeurodataWithoutBorders/pynwb)**
and **[HDMF](https://github.com/hdmf-dev/hdmf)**, developed by Oliver Rübel, Andrew Tritt, Ryan Ly,
Benjamin Dichter, Kristofer Bouchard and the NWB team at **Lawrence Berkeley National Laboratory**
and partners (Rübel et al. 2022, eLife, [10.7554/eLife.78362](https://doi.org/10.7554/eLife.78362);
Tritt et al. 2019, [10.1109/BigData47090.2019.9005648](https://doi.org/10.1109/BigData47090.2019.9005648));
the **[NWB Inspector](https://github.com/NeurodataWithoutBorders/nwbinspector)** by Cody Baker, Ben
Dichter, Ryan Ly, Steph Prince, Heberto Mayorquin, Szonja Weigl, Alessandra Trapani, Oliver Rübel
and contributors (© Lawrence Berkeley National Laboratory; Zenodo [10.5281/zenodo.10611726](https://doi.org/10.5281/zenodo.10611726));
and the **[DANDI client](https://github.com/dandi/dandi-cli)** by Yaroslav Halchenko, John T. Wodder
II, Satrajit Ghosh and the DANDI Archive team (Zenodo
[10.5281/zenodo.3692138](https://doi.org/10.5281/zenodo.3692138)). **Pennsieve packages these tools
as a workflow step; it did not develop them.** It was tested on DANDI datasets by the International
Brain Laboratory (DANDI:000409), Viktor Plusnin and Nikita Pospelov (DANDI:002047), the Allen
Institute (DANDI:000728, published by Cody Baker), Andres Grosmark and György Buzsáki (DANDI:000044)
and Steeve Laquitaine, Milo Imbeni, Joseph Tharayil, James Isbister and Michael Reimann
(DANDI:001250); DOIs under [Citations](#citations).

**What it does.** "Is my NWB file valid, and can I put it on DANDI?" For every NWB file in the input
(HDF5 `.nwb` files and NWB-Zarr folders, found anywhere in the input) it

1. **validates the file against the NWB schema** with PyNWB, using the schema saved inside the file,
   so extension types (ndx-pose, ndx-ibl, ...) are checked against the exact version that wrote them;
2. runs the **NWB Inspector**'s best-practice checks (units, timestamps, compression, metadata, ...),
   with its DANDI configuration by default (a missing subject id, species, sex or age is critical);
3. checks **DANDI upload readiness** offline with the dandi library: the checks `dandi validate`
   runs on a single file, DANDI's own metadata extraction and schema model (is the species one DANDI
   recognises, is the age an ISO 8601 duration such as `P90D`, ...), external links, and the name
   `dandi organize` would give the file (`sub-<id>/sub-<id>_ses-<id>_<modality>.nwb`);
4. **summarises what is in the file**: NWB version, identifier, session start, the time span of the
   data, subject, devices, electrode groups and probes, every time series (type, shape, rate or
   timestamps, unit), Units (count, labels such as good/mua, brain areas), ophys (imaging planes,
   ROIs, ROI series), ndx-pose (keypoints, frames), interval tables (trials and their columns,
   epochs, behavioural states), extensions, file size, and the chunking and compression of the
   largest datasets;
5. draws **previews** from small slices: a 60 s spike raster, a few ΔF/F traces, one pose frame, and
   a timeline of all interval tables.

Each file gets a status: **pass** (no critical problem, no best-practice violation), **warn**
(best-practice violations: valid NWB that should be fixed before sharing) or **fail** (a schema
error, or something NWB Inspector or DANDI rate critical; DANDI would refuse it), and a separate
**DANDI-ready** flag. `report.pdf` is written for a PI or data manager: a cover page with every file
and its status, then a page per file with its contents and issues, and a page of previews.

It runs on its own ("check my lab's files") and as the last step of any workflow
(`ephys-curate`, `ophys-traces`, `pose-kinematics`, ... `→ nwb-inspect`). With `FAIL_ON=critical` it
is a gate: the step fails, after writing its report, when any file has status fail.

For a computational analyst: schema validation is `pynwb.validate(path, use_cached_namespaces=True)`
(for NWB-Zarr, on an open `NWBZarrIO`, because PyNWB 4.2's path-based call passes HDF5-only
arguments to Zarr); the inspector is `nwbinspector.inspect_nwbfile(..., skip_validate=True,
config=load_config("dandi"))` with the chosen importance threshold; the DANDI step calls
`dandi.metadata.nwb.get_metadata` / `nwb2asset` and validates the result with dandischema's
`BareAsset` model (what `dandi upload` sends), and `dandi.organize.create_unique_filenames_from_metadata`
for the organised name. When the inspector did not run with the DANDI configuration, the DANDI step
runs NWB Inspector's DANDI-critical checks itself. The summary and previews read the HDF5/Zarr tree
directly (h5py/zarr: attributes, shapes, a first and last timestamp, bounded slices), not through
PyNWB objects.

## Ports

| Port | Direction | What |
|---|---|---|
| `nwb` | in | One or more NWB files: `.nwb` (HDF5) files and NWB-Zarr folders (`*.nwb.zarr`), anywhere under the input, following links. Other files are ignored; a file named `.nwb` that is not HDF5 is logged and skipped. Optional `sessions.csv` (`session_id, path, ...`) names the sessions. Media types `application/x-hdf5; profile=nwb`, `application/vnd.pennsieve.nwb-zarr` (`container: directory`). |
| `report` | out | `nwb-inspect/` with the files below. |

## Parameters

| Parameter | Default | What it does |
|---|---|---|
| `CHECKS` | `schema,inspector,dandi` | Which validations to run (comma-separated); `none` = summary and previews only. |
| `INSPECTOR_CONFIG` | `dandi` | NWB Inspector configuration: `dandi` (subject id, species, sex, age critical, as DANDI requires) or `default` (NWB Inspector's own levels). The `dandi` check applies DANDI's rules either way. |
| `IMPORTANCE_THRESHOLD` | `BEST_PRACTICE_SUGGESTION` | Lowest importance reported: `BEST_PRACTICE_SUGGESTION`, `BEST_PRACTICE_VIOLATION` or `CRITICAL`. Lower messages are left out of every output and of the status. |
| `FAIL_ON` | `none` | `none`: the step always succeeds and reports. `critical`: exit 1 (after writing everything) when any file has status fail. |
| `PREVIEWS` | `true` | Draw the previews. |
| `LABEL` | (empty) | Extra folder level `nwb-inspect/<LABEL>/` when the app runs more than once in a workflow. |
| `THREADS` | `0` | Threads for numpy/BLAS; 0 = from the container's CPU quota. |

## Outputs (`nwb-inspect/`)

- `report.pdf`: cover page (all files: size, status, counts of critical / violation / suggestion,
  DANDI-ready), then per file a page with its contents and its issues grouped by importance and check
  (count, an example object path, the message), and a page with the previews and their captions.
  Matplotlib's PDF backend with its bundled DejaVu fonts: no fonts or engines to install, Lambda-safe.
- `report.json`: `parameters`, `tools` (versions), `n_status`, `n_dandi_ready`, and per file: `file`,
  `file_id`, `session_id`, `format` (`hdf5`/`zarr`), `size_bytes`, `status`, `dandi_ready`, `counts`
  (per importance), `counts_by_group`, `messages` (every message, below), `summary` (the content
  summary), `dandi` (`suggested_path`, `filename_conforms`, the metadata DANDI extracted), `schema`
  (`cached_namespaces`), `previews` (PNG + caption), `timings_s`, `error`.
- `issues.csv`: one row per message: `file, file_id, session_id, status, check_group` (`schema`,
  `inspector`, `dandi`), `importance` (`CRITICAL`, `BEST_PRACTICE_VIOLATION`,
  `BEST_PRACTICE_SUGGESTION`, or `ERROR` when a check could not run on the file), `check_name`
  (e.g. `check_subject_species_exists`, `DtypeError`, `dandi.file_name`), `object_type, object_name,
  location` (path in the file), `message`.
- `summary.json` (for `neuro-report`): per file `status`, `dandi_ready`, `n_critical`,
  `n_violations`, `n_suggestions`, `suggested_dandi_path`, NWB version, identifier, session start,
  duration, subject, species, `n_units`, `n_time_series`, `n_rois`, `n_keypoints`, `n_trials`,
  extensions, file size; `figures` (the previews with captions); `warnings` (one line per failing file).
- `provenance.json` (conventions.md keys); `<file_id>_raster.png`, `_traces.png`, `_pose.png`,
  `_timeline.png` (150 dpi).

`file_id` is the file's session id (`sub-<a>_ses-<b>` or from `sessions.csv`), or the sanitised file
name when several files share a session (an IBL raw and processed file, a source file and its
derived files).

## Large files and memory

Nothing reads a whole dataset. Schema validation and the NWB Inspector look at attributes, shapes and
dtypes, and NWB Inspector's data checks read their first few hundred elements (for example
`check_timestamps_ascending` looks at the first 200 timestamps, so a reversal later in a long series
is not seen). The summary reads the first and last timestamp of each series, label and area columns
of tables up to 200,000 rows, and the dataset metadata (chunks, filters, bytes stored). The previews
read at most 150 units' spikes in a 60 s window (spike times read once, in 2.5-million-value blocks,
up to 200 million spikes), 6,000 samples of 64 ROIs, one frame of each keypoint plus 600 frames of
one, and 20,000 rows per interval table. So run time grows with the number of objects in the file,
not its size: the 6.1 GB IBL raw cut took 18 s and the 5.1 GB Grosmark file 51 s (under emulation;
most of it importing libraries and reading the schema), at 0.8 GB peak memory or less. The exceptions are files with
hundreds of millions of spikes (the raster stops reading at 200 million) and files with tens of
thousands of objects (the inspector walks every one); a run over many files is bounded by the 900 s
step limit, so split very large batches across steps.

## Runtime

`cpu: 1024`, `memory: 2048`, `timeoutSeconds: 900`: within the Lambda limits (the platform decides).
Measured in Docker, linux/amd64 under emulation on an M-series Mac shared with other builds (native
amd64 is several times faster), read-only root file system, uid 65534, `--memory 4g`, default
parameters. Wall = the app's own time; peak memory = the container's `memory.peak`:

| Input | Files | Wall (app) | Peak memory (cgroup) |
|---|---|---|---|
| IBL (`data/ibl/`): processed 0.5 GB + raw cut 6.1 GB | 2 | 156 s (126 s + 18 s) | 0.79 GB |
| DANDI 002047 (6 sessions) + pose-kinematics and behavior-syllables outputs | 18 | 358 s (source 28-60 s, outputs 3-15 s each) | 0.73 GB |
| Allen Visual Coding 2p, 0.8 GB | 1 | 41 s | 0.42 GB |
| Grosmark, 5.1 GB | 1 | 57 s | 0.46 GB |
| Ground truth (DANDI 001250), 0.6 GB | 1 | 39 s | 0.41 GB |
| Synthetic fixture (7 files incl. 64 MB uncompressed and NWB-Zarr) | 7 | 41.5 s | 0.36 GB |

Image: 0.64 GB uncompressed, 0.21 GB compressed (python:3.12-slim plus PyNWB, NWB Inspector, dandi, hdmf-zarr, Matplotlib, with
precompiled byte code: the root file system is read-only at run time, and compiling the libraries on
every start took minutes under emulation).

No network at run time: dandi's version check is off (`DANDI_NO_ET=1`); its ontology lookup of
NCBITaxon URLs it does not know is replaced by an immediate offline failure (the URL is then kept, as
dandi does when offline); dandischema's metadata model, NWB Inspector's DANDI configuration and Allen
CCF names, and the fonts ship inside the packages. The tests block all sockets and pass.

## Results on the demo data

Reports are in `data/work/<demo>/nwb-inspect/` of the workflow repository.

| File | Status | Critical / violations / suggestions | DANDI-ready | What it found |
|---|---|---|---|---|
| IBL processed (000409) | warn | 0 / 28 / 11 | yes | pose units `px` instead of `pixels` (16 series), 12 electrode locations that are not Allen CCF terms (e.g. "Dentate gyrus molecular layer"), non-standard module names (`wheel`, `pupil`, ...), no experimenter/keywords. 1,359 units, 404 trials, 3 cameras of Lightning Pose. |
| IBL raw cut (ours) | warn | 0 / 8 / 3 | yes | the same CCF names on the electrodes; no experimenter, keywords; an all-NaN `imp` column. |
| DANDI 002047, 6 sessions | fail | 1 / 0 / 1-3 | yes | `MotionCorrectedVideo` points at an external mp4 that is not next to the file: our staging copied only the behaviour video, so this is expected locally (on DANDI the asset exists). Otherwise clean. |
| behavior-syllables outputs (6) | fail | 1 / 0 / 5 | **no** | schema error: `general/source_script` has no `file_name` attribute (PyNWB requires it when `source_script` is set). Also no `session_id`, experimenter, institution, keywords, experiment description. |
| pose-kinematics outputs (6) | warn | 0 / 15 / 5 | yes | unit `cm` on 15 SpatialSeries (NWB wants `centimeters`); no `session_id`, experimenter, institution, keywords, experiment description. |
| Allen Visual Coding 2p (000728) | warn | 0 / 2 / 3 | yes | `IndexSeries` pointing at a `TimeSeries` (deprecated); 353 ROIs. |
| Grosmark (000044) | pass | 0 / 0 / 0 | yes | 68 units, 66 trials. |
| Ground truth (001250) | warn | 0 / 1 / 4 | yes | Units without `resolution`; the 0.6 GB raw `ElectricalSeries` is stored uncompressed; experimenter not in "Last, First" form. |

The synthetic fixture: the clean file passes (HDF5 and NWB-Zarr); missing species → critical,
DANDI-blocking; empty unit → `check_missing_unit`; timestamps going backwards →
`check_timestamps_ascending`; `rate` written as text → schema `DtypeError` (fail); the 64 MB
uncompressed dataset → `check_small_dataset_compression` (a suggestion in NWB Inspector below 10 GB)
and flagged in the storage summary.

## Limitations

- It checks **form, not content**: valid NWB with plausible metadata can still hold a mis-sorted
  recording or the wrong session clock. The previews and the timeline are there for a human to look.
- NWB Inspector samples data (first elements); a problem only later in a dataset can be missed.
- The DANDI check is the single-file part of `dandi validate` / `dandi upload`. Dandiset-level
  metadata (`dandiset.yaml`: contributors, licence, description), BIDS validation and server-side
  checks need a dandiset and the network and are not run.
- NWB-Zarr: dandi 0.82 extracts metadata from HDF5 NWB only, so for Zarr files only the
  DANDI-critical NWB Inspector checks run; NWB Inspector 0.7.2's two compression checks crash on zarr 3
  arrays and are skipped for Zarr (the summary shows the codecs instead).
- External files (videos referenced by `ImageSeries.external_file`) are checked by NWB Inspector
  relative to the NWB file; if they were not uploaded alongside, that is reported as critical.
- An IBL-style file can be valid and DANDI-ready and still have best-practice violations (e.g. `px`
  instead of `pixels` as a unit); "warn" is not a reason to distrust the data.

## Development

```
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test PYTHON=.venv/bin/python      # fixture through the processor, no Docker (~1 min)
make run                               # Docker over data/fixture/, outputs in data/output/
```

`tests/make_fixture.py` writes a clean file and one file per planted problem (missing species,
empty unit, timestamps going backwards, a schema dtype error, a 64 MB uncompressed dataset) and the
clean file as NWB-Zarr; the tests assert each is caught by the right check and the clean files pass.
The review run of a release uses the committed copies in `sample-input/review/` (the platform's
generator image has no PyNWB).

## Licences

Apache-2.0 (this repository). Everything in the image is BSD, MIT, Apache-2.0, MPL-2.0 or similar;
no GPL code is imported (`rfc3987`, an optional GPL dependency of `jsonschema[format]`, is left out on
purpose). See `THIRD_PARTY.md`.

## Citations

Please cite these works if you use this app. Verified on Crossref/DataCite and PubMed; full author
lists in CITATION.cff.

- Oliver Rübel, Andrew Tritt, Ryan Ly, Benjamin K Dichter, Satrajit Ghosh, Lawrence Niu, Pamela
  Baker, Ivan Soltesz, Lydia Ng, Karel Svoboda, Loren Frank, Kristofer E Bouchard (2022). The
  Neurodata Without Borders ecosystem for neurophysiological data science. *eLife* 11:e78362.
  doi:[10.7554/eLife.78362](https://doi.org/10.7554/eLife.78362), PMID:36193886.
- Andrew J. Tritt, Oliver Rubel, Benjamin Dichter, Ryan Ly, Donghe Kang, Edward F. Chang, Loren M.
  Frank, Kristofer Bouchard (2019). HDMF: Hierarchical Data Modeling Framework for Modern Science
  Data Standards. *2019 IEEE International Conference on Big Data (Big Data)*, 165-179.
  doi:[10.1109/BigData47090.2019.9005648](https://doi.org/10.1109/BigData47090.2019.9005648), PMID:34632466.
- Baker C, Dichter B, Ly R, et al. NeurodataWithoutBorders/nwbinspector (software, v0.7.2), Zenodo,
  doi:[10.5281/zenodo.10611726](https://doi.org/10.5281/zenodo.10611726).
- Tritt A, Dichter B, Ruebel O, Ly R, et al. NeurodataWithoutBorders/pynwb (software), Zenodo,
  doi:[10.5281/zenodo.10582180](https://doi.org/10.5281/zenodo.10582180).
- Tritt A, Ly R, Dichter B, Ruebel O, et al. hdmf-dev/hdmf (software), Zenodo,
  doi:[10.5281/zenodo.8034516](https://doi.org/10.5281/zenodo.8034516).
- Halchenko Y, Wodder JT II, Christian H, Ghosh S, et al. dandi/dandi-cli (software, 0.82.0), Zenodo,
  doi:[10.5281/zenodo.3692138](https://doi.org/10.5281/zenodo.3692138).
- John D. Hunter (2007). Matplotlib: A 2D Graphics Environment. *Computing in Science & Engineering*
  9:90-95. doi:[10.1109/MCSE.2007.55](https://doi.org/10.1109/MCSE.2007.55).

Test data (CC-BY-4.0):

- International Brain Laboratory (2026). IBL - Brain Wide Map. DANDI:000409,
  doi:[10.48324/dandi.000409/0.260309.1324](https://doi.org/10.48324/dandi.000409/0.260309.1324).
- Viktor Plusnin, Nikita Pospelov (2026). Hippocampal CA1 one-photon calcium imaging and
  pose-tracked behavior in wild-type and 5xFAD mice across four behavioral paradigms. DANDI:002047,
  doi:[10.48324/dandi.002047/0.261106.0903](https://doi.org/10.48324/dandi.002047/0.261106.0903).
- Cody Baker (2024). Allen Institute - Visual Coding - Optical Physiology. DANDI:000728,
  doi:[10.48324/dandi.000728/0.240827.1809](https://doi.org/10.48324/dandi.000728/0.240827.1809).
- Andres D. Grosmark, György Buzsáki (2026). Diversity in neural firing dynamics supports both rigid
  and learned hippocampal sequences. DANDI:000044,
  doi:[10.48324/dandi.000044/0.261106.0236](https://doi.org/10.48324/dandi.000044/0.261106.0236).
- Steeve Laquitaine, Milo Imbeni, Joseph Tharayil, James Isbister, Michael Reimann (2026). Spike
  sorting biases and information loss in a detailed cortical model. DANDI:001250,
  doi:[10.48324/dandi.001250/0.261108.1908](https://doi.org/10.48324/dandi.001250/0.261108.1908).

## Acknowledgements

NWB, PyNWB and HDMF are developed by the Neurodata Without Borders community and team (Lawrence
Berkeley National Laboratory and partners); the NWB Inspector by its contributors and the NWB team; the
dandi client and dandischema by the DANDI Archive team (https://dandiarchive.org). We thank the
International Brain Laboratory, the Allen Institute, the Buzsáki lab, the authors of DANDI:002047 and
of DANDI:001250 for sharing the datasets used to test this app.
