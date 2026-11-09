"""
A small read-only view of an NWB file's object tree that works the same for HDF5 (h5py) and Zarr
(zarr) files, without building PyNWB objects: the content summary and the previews only need
neurodata types, attributes, dataset shapes and a few small slices. Nothing here reads a whole
dataset unless the caller asks for a bounded slice.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _s(v):
    """Attribute / scalar to a plain Python value (bytes -> str, 0-d arrays -> scalars)."""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.ndarray):
        if v.ndim == 0:
            return _s(v[()])
        return [_s(x) for x in v.tolist()]
    if isinstance(v, (np.generic,)):
        return v.item()
    if isinstance(v, (list, tuple)):
        return [_s(x) for x in v]
    return v


class Tree:
    """Opened NWB file: `group(path)`, `is_group`, `attrs`, `dataset` access by path."""

    def __init__(self, path: Path, fmt: str):
        self.path = Path(path)
        self.fmt = fmt
        if fmt == "zarr":
            import zarr

            self.root = zarr.open_group(str(path), mode="r")
        else:
            import h5py

            self.root = h5py.File(str(path), "r")

    def close(self):
        if self.fmt != "zarr":
            try:
                self.root.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- navigation
    def get(self, path: str):
        path = path.strip("/")
        if not path:
            return self.root
        try:
            obj = self.root[path]
        except (KeyError, ValueError):
            return None
        return obj

    def is_group(self, obj) -> bool:
        if self.fmt == "zarr":
            return not hasattr(obj, "shape")
        import h5py

        return isinstance(obj, h5py.Group)

    def keys(self, obj) -> list[str]:
        try:
            return sorted(obj.keys())
        except Exception:
            return []

    def attr(self, obj, name, default=None):
        try:
            if name in obj.attrs:
                v = _s(obj.attrs[name])
                if self.fmt == "zarr" and isinstance(v, dict) and "path" in v:
                    return v  # a Zarr object reference
                return v
        except Exception:
            pass
        return default

    def ntype(self, obj) -> str | None:
        return self.attr(obj, "neurodata_type")

    def scalar(self, path_or_obj, default=None):
        obj = self.get(path_or_obj) if isinstance(path_or_obj, str) else path_or_obj
        if obj is None or self.is_group(obj):
            return default
        try:
            if obj.shape == ():
                return _s(obj[()])
            if len(obj.shape) == 1 and obj.shape[0] <= 64:
                return _s(obj[:])
        except Exception:
            return default
        return default

    def shape(self, obj) -> tuple:
        try:
            return tuple(int(x) for x in obj.shape)
        except Exception:
            return ()

    def dtype(self, obj) -> str:
        try:
            return str(obj.dtype)
        except Exception:
            return ""

    def child_name(self, obj, key: str) -> str | None:
        """Name (last path component) of a linked object, e.g. ElectrodeGroup.device -> 'Probe01'."""
        try:
            if self.fmt == "zarr":
                links = self.attr(obj, "zarr_link") or []
                for ln in links if isinstance(links, list) else []:
                    if ln.get("name") == key:
                        return str(ln.get("path", "")).rstrip("/").split("/")[-1]
                return None
            target = obj.get(key)
            if target is None:
                return None
            return target.name.rstrip("/").split("/")[-1]
        except Exception:
            return None

    def walk(self):
        """(path, obj) for every group with a neurodata_type, breadth-first, without following links twice."""
        out = []
        stack = [("", self.root)]
        while stack:
            p, g = stack.pop(0)
            for k in self.keys(g):
                if self.fmt != "zarr":
                    import h5py

                    try:
                        if isinstance(g.get(k, getlink=True), (h5py.SoftLink, h5py.ExternalLink)):
                            continue  # a link to an object stored (and listed) at its own place
                    except Exception:
                        continue
                try:
                    o = g[k]
                except Exception:
                    continue
                cp = f"{p}/{k}"
                if self.is_group(o):
                    if self.ntype(o):
                        out.append((cp, o))
                    if k != "specifications":
                        stack.append((cp, o))
        return out

    def datasets(self):
        """(path, dataset) for every dataset under the root (no specifications)."""
        out = []
        if self.fmt != "zarr":
            import h5py

            def visit(name, obj):
                if isinstance(obj, h5py.Dataset) and not name.startswith("specifications"):
                    out.append(("/" + name, obj))

            self.root.visititems(visit)
            return out
        stack = [("", self.root)]
        while stack:
            p, g = stack.pop()
            for k in self.keys(g):
                if p == "" and k == "specifications":
                    continue
                try:
                    o = g[k]
                except Exception:
                    continue
                cp = f"{p}/{k}"
                if self.is_group(o):
                    stack.append((cp, o))
                else:
                    out.append((cp, o))
        return out

    def storage(self, ds) -> dict:
        """Chunking, compression and bytes on disk of one dataset."""
        shape = self.shape(ds)
        try:
            itemsize = ds.dtype.itemsize
        except Exception:
            itemsize = 0
        n = int(np.prod(shape)) if shape else 1
        info = {"shape": list(shape), "dtype": self.dtype(ds), "nbytes": n * itemsize, "chunks": None,
                "compression": None, "compression_opts": None, "stored_bytes": None}
        if self.fmt == "zarr":
            try:
                info["chunks"] = list(ds.chunks)
                comps = getattr(ds, "compressors", None) or ()
                info["compression"] = ",".join(type(c).__name__ for c in comps) or None
                info["stored_bytes"] = int(ds.nbytes_stored()) if hasattr(ds, "nbytes_stored") else None
            except Exception:
                pass
            return info
        try:
            info["chunks"] = list(ds.chunks) if ds.chunks else None
            info["compression"] = ds.compression
            info["compression_opts"] = _s(ds.compression_opts) if ds.compression_opts is not None else None
            filters = ds._filters if hasattr(ds, "_filters") else {}
            if not info["compression"] and filters:
                other = [str(k) for k in filters if k not in ("shuffle", "fletcher32", "scaleoffset")]
                info["compression"] = ",".join(other) or None
            info["stored_bytes"] = int(ds.id.get_storage_size())
        except Exception:
            pass
        return info

    def specifications(self) -> dict:
        spec = self.get("specifications")
        if spec is None:
            return {}
        return {k: self.keys(spec[k]) for k in self.keys(spec)}
