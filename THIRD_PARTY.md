# Third-party software

This app is Apache-2.0 (see `LICENSE`). The image contains these third-party components, installed
from PyPI at the pinned versions in `requirements.txt`; their licences apply to the image. Licences
were read from each installed package's metadata in the built image (`importlib.metadata`).
**No GPL code is imported.** `rfc3987` (GPL-3.0-or-later), an optional extra of `jsonschema[format]`
that dandischema asks for, is deliberately left out of the image: jsonschema would import it
in-process, and it is only needed for the `iri` string format, which nothing here validates.

| Component | Authors / copyright holder | What | Licence | Source |
|---|---|---|---|---|
| NWB Inspector 0.7.2 | Cody Baker, Ben Dichter, Ryan Ly, Steph Prince, Heberto Mayorquin, Szonja Weigl, Alessandra Trapani, Oliver Rübel and contributors; © The Regents of the University of California, through Lawrence Berkeley National Laboratory | Best-practice checks, its DANDI configuration | BSD-3-Clause (LBNL variant) | https://github.com/NeurodataWithoutBorders/nwbinspector |
| PyNWB 4.2.0 | Andrew Tritt, Ben Dichter, Oliver Rübel, Ryan Ly and the NWB team; © The Regents of the University of California (LBNL) | Reading NWB, schema validation (`pynwb.validate`) | BSD-3-Clause | https://github.com/NeurodataWithoutBorders/pynwb |
| HDMF 6.2.0, hdmf-zarr 0.14.0 | Andrew Tritt, Ryan Ly, Oliver Rübel, Ben Dichter, Matthew Avaylon and the HDMF team; © The Regents of the University of California (LBNL) | Schema/IO layer of PyNWB, the validator, NWB-Zarr | BSD-3-Clause | https://github.com/hdmf-dev/hdmf, https://github.com/hdmf-dev/hdmf-zarr |
| dandi 0.82.0 (dandi-cli), dandischema 0.14.0 | Yaroslav Halchenko, John T. Wodder II, Satrajit Ghosh, Cody Baker, Dorota Jarecka and the DANDI team (DANDI Archive) | DANDI metadata extraction, the asset metadata model, `dandi organize` file names; bundled Allen CCF structure table | Apache-2.0 | https://github.com/dandi/dandi-cli, https://github.com/dandi/dandi-schema |
| h5py 3.16.0 (with HDF5) | Andrew Collette and h5py contributors; The HDF Group | HDF5 access | BSD-3-Clause (HDF5: BSD-3-Clause-style) | https://www.h5py.org |
| zarr 3.4.2, numcodecs 0.17.1, tensorstore 0.1.86, zarr-checksum | zarr developers; Google (tensorstore); DANDI (zarr-checksum) | NWB-Zarr access; dependencies of dandi | MIT; Apache-2.0 | https://zarr.dev |
| Matplotlib 3.11.2 (with DejaVu fonts) | John D. Hunter, Michael Droettboom and the Matplotlib Development Team; DejaVu fonts: Bitstream, DejaVu authors | Previews, report.pdf | Matplotlib licence (PSF-based); fonts: Bitstream Vera / DejaVu licence | https://matplotlib.org |
| NumPy 2.5.4, pandas 3.1.1 | NumPy and pandas developers | Arrays, tables | BSD-3-Clause (NumPy: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0) | numpy.org, pandas.pydata.org |
| pydantic 2.14, pydantic-core | Samuel Colvin and pydantic contributors | dandischema's model | MIT | https://github.com/pydantic/pydantic |
| bids-validator-deno 3.0.2, deno 2.9.8, bidsschematools 1.2.7 | BIDS contributors; Deno Land Inc. | Dependencies of dandi (BIDS validation; not used here) | MIT | PyPI |
| keyring, keyrings.alt, SecretStorage, jeepney, pycryptodomex, cryptography | respective developers | Dependencies of dandi (credentials; not used here) | MIT, BSD-3-Clause, Apache-2.0 OR BSD-3-Clause, BSD / Public Domain | PyPI |
| certifi, tqdm, fqdn, jinxed | respective developers | Dependencies; shipped unmodified | MPL-2.0 (tqdm: MPL-2.0 AND MIT) | PyPI |
| email-validator | Joshua Tauberer | Dependency of dandischema | Unlicense | PyPI |
| Other transitive dependencies (aiohttp, attrs, click, jsonschema, PyYAML, requests, ruamel.yaml, tenacity, urllib3, yarl, fonttools, Pillow, kiwisolver, contourpy, isoduration, ...) | respective developers | Versions in `requirements.txt` | MIT / BSD / Apache-2.0 / PSF-2.0 / ISC / MIT-CMU (Pillow) | PyPI |
| python:3.12.16-slim-bookworm | Python Software Foundation, Debian | Base image | PSF-2.0 (Python); Debian packages under their own free licences | https://hub.docker.com/_/python |

## Not bundled

- **Test and demo data** (not in the image): the synthetic files in `sample-input/review/` are made
  by `tests/make_fixture.py` (Apache-2.0, this repository). The demo files the README reports on are
  DANDI datasets under CC-BY-4.0: DANDI:000409 (International Brain Laboratory,
  doi:10.48324/dandi.000409/0.260309.1324), DANDI:002047 (Plusnin, Pospelov,
  doi:10.48324/dandi.002047/0.261106.0903), DANDI:000728 (Baker, doi:10.48324/dandi.000728/0.240827.1809),
  DANDI:000044 (Grosmark, Buzsáki, doi:10.48324/dandi.000044/0.261106.0236), DANDI:001250
  (Laquitaine et al., doi:10.48324/dandi.001250/0.261108.1908).
- **ndx-pose** is used only by the test fixture generator (`requirements-dev.txt`); the app reads
  extension types from the namespaces cached in each file.
