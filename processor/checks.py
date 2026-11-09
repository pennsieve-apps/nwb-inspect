"""
The three validations, each returning a list of issue dicts with the same keys:

  check_group   schema | inspector | dandi
  importance    CRITICAL | BEST_PRACTICE_VIOLATION | BEST_PRACTICE_SUGGESTION | ERROR
                (ERROR = a check could not run, e.g. it crashed on this file)
  check_name    e.g. check_subject_species_exists, MissingError, dandi.species
  object_type, object_name, location (path inside the file), message

1. schema: PyNWB's validator (pynwb.validate) against the namespaces cached in the file, so extension
   types (ndx-pose, ndx-ibl, ...) are validated against the exact version that wrote them.
2. inspector: NWB Inspector best-practice checks, with its DANDI configuration or its default one.
3. dandi: what `dandi validate` / `dandi upload` / `dandi organize` need from a single file, offline:
   the DANDI-critical NWB Inspector checks (subject id, species, sex, age), DANDI's own metadata
   extraction and its dandischema model (species and age must be interpretable, ...), external links,
   NWB version, and the organised file name `dandi organize` would give the file.

Nothing here touches the network: DANDI's version check is off (DANDI_NO_ET), its ontology lookup of
unknown NCBITaxon URLs is replaced by an offline failure, and dandischema's model is the one bundled.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

IMPORTANCE_ORDER = ["CRITICAL", "BEST_PRACTICE_VIOLATION", "BEST_PRACTICE_SUGGESTION"]
IMPORTANCE_RANK = {"ERROR": 3, "CRITICAL": 2, "BEST_PRACTICE_VIOLATION": 1, "BEST_PRACTICE_SUGGESTION": 0}

# The checks NWB Inspector's own DANDI configuration raises to CRITICAL ("required for dandi validate to
# pass"); run by the dandi step when the inspector step did not already run them with that configuration.
DANDI_CRITICAL_CHECKS = None  # read from nwbinspector's config at first use

log = logging.getLogger("nwb-inspect")


def issue(group, importance, check, message, object_type="", object_name="", location=""):
    return {
        "check_group": group,
        "importance": importance,
        "check_name": check,
        "object_type": object_type or "",
        "object_name": object_name or "",
        "location": location or "",
        "message": str(message).strip(),
    }


# --------------------------------------------------------------------------------------------- schema
def run_schema(path: Path) -> tuple[list[dict], dict]:
    """PyNWB validation against the file's cached namespaces (falls back to the core schema)."""
    import pynwb

    info = {"cached_namespaces": _has_cached_spec(path)}
    out = []
    try:
        if path.is_dir():
            # NWB-Zarr: pynwb 4.2's validate(path=...) passes HDF5-only arguments to ZarrIO; give it an open IO.
            from hdmf_zarr import NWBZarrIO

            with NWBZarrIO(str(path), mode="r") as io:
                errors = pynwb.validate(io=io, use_cached_namespaces=True)
        else:
            errors = pynwb.validate(path=str(path), use_cached_namespaces=True)
    except Exception as e:  # unreadable, wrong format, broken namespace
        return [issue("schema", "CRITICAL", "schema.read_error",
                      f"PyNWB could not open the file for validation: {type(e).__name__}: {e}")], info
    if not info["cached_namespaces"]:
        out.append(issue("schema", "BEST_PRACTICE_VIOLATION", "schema.no_cached_namespaces",
                         "The file has no cached namespaces (the schema was not saved in the file); it was "
                         "validated against PyNWB's core schema only, and extension types could not be checked. "
                         "Write NWB files with cache_spec=True (the PyNWB default)."))
    for e in errors:
        name = type(e).__name__
        loc = getattr(e, "location", None) or ""
        obj = getattr(e, "name", "") or ""
        reason = getattr(e, "reason", None) or str(e)
        out.append(issue("schema", "CRITICAL", name, reason, object_type="", object_name=obj, location=loc))
    return out, info


def _has_cached_spec(path: Path) -> bool:
    try:
        if path.is_dir():
            return (path / "specifications").is_dir()
        import h5py

        with h5py.File(str(path), "r") as f:
            return "specifications" in f and len(f["specifications"]) > 0
    except Exception:
        return False


# ------------------------------------------------------------------------------------------ inspector
def _inspector_messages(path: Path, fmt: str, config_name: str, threshold: str, select=None) -> list[dict]:
    from nwbinspector import Importance, inspect_nwbfile, inspect_nwbfile_object, load_config

    config = load_config(filepath_or_keyword="dandi") if config_name == "dandi" else None
    thr = Importance[threshold]
    if fmt == "zarr":
        from hdmf_zarr import NWBZarrIO

        with NWBZarrIO(str(path), mode="r") as io:
            nwb = io.read()
            # NWB Inspector 0.7.2's compression checks read `.compressor`, which zarr 3 arrays no longer have
            # (TypeError on every dataset); the content summary reports Zarr compression instead.
            ignore = None if select else ["check_large_dataset_compression", "check_small_dataset_compression"]
            msgs = list(inspect_nwbfile_object(nwbfile_object=nwb, config=config, importance_threshold=thr,
                                               select=select, ignore=ignore))
    else:
        msgs = list(inspect_nwbfile(nwbfile_path=str(path), skip_validate=True, config=config,
                                    importance_threshold=thr, select=select))
    out = []
    for m in msgs:
        if m is None:
            continue
        imp = m.importance.name
        if imp == "PYNWB_VALIDATION":  # only when skip_validate=False; kept for completeness
            imp = "CRITICAL"
        check, text = m.check_function_name, m.message
        if imp == "ERROR":
            # a check that crashed (or a file PyNWB cannot read): keep the check's name and the error, not the
            # whole traceback
            mm = re.search(r"During evaluation of '(\w+)'", check or "")
            lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
            last = next((ln for ln in reversed(lines) if re.match(r"^[\w.]+(Error|Exception)\b", ln)), lines[-1] if lines else "")
            if mm:
                check, text = mm.group(1), f"This check could not run on this file: {last}"
            else:
                check, text = "inspector.read_error", f"NWB Inspector could not read the file: {check} {last}"
        out.append(issue("inspector", imp, check, text, m.object_type, m.object_name, m.location or ""))
    return out


def run_inspector(path: Path, fmt: str, config_name: str, threshold: str) -> list[dict]:
    try:
        return _inspector_messages(path, fmt, config_name, threshold)
    except Exception as e:
        return [issue("inspector", "ERROR", "inspector.read_error",
                      f"NWB Inspector could not inspect the file: {type(e).__name__}: {e}")]


def dandi_critical_checks() -> list[str]:
    global DANDI_CRITICAL_CHECKS
    if DANDI_CRITICAL_CHECKS is None:
        from nwbinspector import load_config

        DANDI_CRITICAL_CHECKS = list(load_config(filepath_or_keyword="dandi").get("CRITICAL", []))
    return DANDI_CRITICAL_CHECKS


# ---------------------------------------------------------------------------------------------- dandi
def _offline_dandi():
    """Make dandi's metadata extraction offline: an NCBITaxon URL that is not in dandi's bundled species
    table would be looked up on ontobee.org; fail that lookup immediately (dandi then keeps the URL)."""
    import dandi.metadata.util as du

    def _no_network(url, lookup=None):
        raise ConnectionError("offline (nwb-inspect has no network access)")

    du.parse_purlobourl = _no_network


def run_dandi(path: Path, fmt: str, inspector_issues: list[dict] | None, inspector_config: str,
              threshold: str) -> tuple[list[dict], dict]:
    """DANDI upload readiness of one file. `inspector_issues` are the inspector step's messages when it ran
    with the DANDI configuration (then its CRITICAL ones are not repeated here)."""
    out: list[dict] = []
    info: dict = {"suggested_path": None, "filename_conforms": None, "metadata": {}}

    # 1. NWB Inspector's DANDI-critical checks (subject, species, sex, age, ids without slashes).
    if inspector_issues is None or inspector_config != "dandi":
        try:
            msgs = _inspector_messages(path, fmt, "dandi", "CRITICAL", select=dandi_critical_checks())
        except Exception as e:
            msgs = [issue("dandi", "ERROR", "dandi.inspector_error", f"{type(e).__name__}: {e}")]
        for m in msgs:
            m["check_group"] = "dandi"
            out.append(m)

    if fmt == "zarr":
        out.append(issue("dandi", "BEST_PRACTICE_SUGGESTION", "dandi.zarr_nwb",
                         "NWB-Zarr: DANDI's metadata extraction (dandi 0.82) reads HDF5 NWB only, so the DANDI "
                         "metadata and file-name checks were skipped; the DANDI-critical NWB Inspector checks above "
                         "still apply. Convert to HDF5 NWB to upload to DANDI with the standard tools."))
        return out, info

    _offline_dandi()
    from dandi.metadata.nwb import get_metadata, nwb2asset
    from dandi.misctypes import DUMMY_DANDI_ETAG
    from dandi.pynwb_utils import get_nwb_version, nwb_has_external_links
    from dandischema.models import BareAsset
    from pydantic import ValidationError

    logging.getLogger("dandi").setLevel(logging.ERROR)

    # 2. External links: dandi refuses to read files that link to other files.
    try:
        if nwb_has_external_links(str(path)):
            out.append(issue("dandi", "CRITICAL", "dandi.external_links",
                             "The file has external links to other HDF5 files; DANDI does not accept these. "
                             "Copy the linked data into the file before uploading."))
            return out, info
    except Exception:
        pass

    # 3. NWB version: dandi requires a parseable version >= 2.1.0 (older files are flagged).
    try:
        v = get_nwb_version(str(path), sanitize=False)
        info["nwb_version"] = v
        m = re.match(r"^(\d+)\.(\d+)", str(v or ""))
        if not v:
            out.append(issue("dandi", "CRITICAL", "dandi.nwb_version", "The file has no nwb_version attribute."))
        elif m and (int(m.group(1)), int(m.group(2))) < (2, 1):
            out.append(issue("dandi", "BEST_PRACTICE_VIOLATION", "dandi.nwb_version",
                             f"NWB version {v} is older than 2.1.0; DANDI's tools may reject it. Re-write with a "
                             "current PyNWB."))
    except Exception:
        pass

    # 4. DANDI's metadata extraction and its schema model (what `dandi upload` sends).
    md = None
    try:
        md = get_metadata(str(path))
    except Exception as e:
        out.append(issue("dandi", "CRITICAL", "dandi.metadata_unreadable",
                         f"DANDI could not extract the file's metadata: {type(e).__name__}: {e}"))
    if md is not None:
        keep = ("nwb_version", "identifier", "session_id", "session_start_time", "subject_id", "species", "sex",
                "age", "date_of_birth", "genotype", "strain", "lab", "institution", "experimenter",
                "keywords", "related_publications", "nd_types")
        info["metadata"] = {k: md.get(k) for k in keep if k in md}
        try:
            asset = nwb2asset(str(path), digest=DUMMY_DANDI_ETAG)
            BareAsset(**asset.model_dump())
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                out.append(issue("dandi", "CRITICAL", "dandi.metadata_invalid",
                                 f"DANDI asset metadata '{loc}': {err.get('msg')}", location=loc))
        except Exception as e:
            msg = str(e)
            check = "dandi.metadata_invalid"
            if "species" in msg.lower():
                check = "dandi.species"
                msg = (f"DANDI cannot interpret the subject's species: {msg.split('. Please')[0]}. Use the Latin "
                       "binomial (e.g. 'Mus musculus') or an NCBITaxon URL "
                       "(http://purl.obolibrary.org/obo/NCBITaxon_10090).")
            elif "age" in msg.lower() or "duration" in msg.lower():
                check = "dandi.age"
            out.append(issue("dandi", "CRITICAL", check, f"{type(e).__name__}: {msg}", object_type="Subject",
                             location="/general/subject"))

        # 5. Session id: dandi organize uses it in the file name; without it, files of one subject collide.
        if not md.get("session_id"):
            out.append(issue("dandi", "BEST_PRACTICE_SUGGESTION", "dandi.session_id",
                             "No session_id: `dandi organize` will derive one from session_start_time. Set "
                             "NWBFile.session_id so files of the same subject get stable, readable names.",
                             object_type="NWBFile", location="/"))

        # 6. File name: what `dandi organize` would call this file.
        try:
            from dandi.organize import ORGANIZED_FILENAME_REGEX, create_unique_filenames_from_metadata

            rec = dict(md, path=str(path))
            if rec.get("subject_id"):
                # With one file dandi would leave the session out (it adds fields only to tell files apart);
                # ask for it, as it would appear once the dandiset has several sessions of this subject.
                res = create_unique_filenames_from_metadata([rec], required_fields=["session_id"])
                info["suggested_path"] = res[0].get("dandi_path")
            conforms = bool(re.fullmatch(ORGANIZED_FILENAME_REGEX, path.name))
            info["filename_conforms"] = conforms
            if not conforms:
                where = (f"; `dandi organize` would place it at {info['suggested_path']}" if info["suggested_path"]
                         else "; `dandi organize` cannot name it without a subject_id")
                out.append(issue("dandi", "BEST_PRACTICE_SUGGESTION", "dandi.file_name",
                                 f"File name '{path.name}' does not follow DANDI's sub-<id>_ses-<id>_<modality>.nwb "
                                 f"layout{where}. Run `dandi organize` before `dandi upload`.", location="/"))
        except Exception as e:
            log.debug("organize suggestion failed: %s", e)

    thr = IMPORTANCE_RANK[threshold]
    out = [i for i in out if IMPORTANCE_RANK.get(i["importance"], 3) >= thr]
    return out, info
