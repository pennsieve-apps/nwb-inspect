FROM python:3.12.16-slim-bookworm@sha256:623674a14ef93d052bb9b0de4dbf5f28eb578a35263838941cc8aa43213c1487

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /processor

# The complete pinned dependency set (requirements.in resolved in this base image; wheels only).
COPY requirements.txt /processor/requirements.txt
# Byte-code is compiled here: the file system is read-only at run time, and compiling ~100 packages
# on every start costs minutes on a cold Lambda.
RUN pip install --no-deps --only-binary=:all: -r /processor/requirements.txt \
    && find /usr/local/lib/python3.12/site-packages -type d -name tests -prune -exec rm -rf {} + \
    && python -m compileall -q -j 0 /usr/local/lib/python3.12/site-packages > /dev/null

COPY processor/ /processor/processor/
COPY VERSION /processor/VERSION
RUN python -m compileall -q /processor/processor

# No network at run time: DANDI_NO_ET turns off dandi's version check; the dandischema model, the
# NWB Inspector configuration and Allen CCF names, and Matplotlib's DejaVu fonts are inside the
# installed packages. Inputs are read-only, so HDF5 file locking is off. Caches (Matplotlib) go to
# $TMPDIR at start-up (processor/common.py): on Lambda only INPUT_DIR, OUTPUT_DIR, HOME and TMPDIR
# are writable and nothing the image put in /tmp or HOME is there.
ENV PYTHONPATH="/processor" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    USER=app \
    LOGNAME=app \
    MPLBACKEND=Agg \
    DANDI_NO_ET=1 \
    HDF5_USE_FILE_LOCKING=FALSE

# Check that the stack imports.
RUN MPLCONFIGDIR=/dev/shm/mpl HOME=/dev/shm python -c "import matplotlib.pyplot, pynwb, hdmf_zarr, nwbinspector, dandi.metadata.nwb, dandi.organize, dandischema.models"

# Runs as uid 1000 on ECS and as an arbitrary unprivileged user on Lambda; nothing here needs root or a
# particular uid (USER=app above answers getpass).
RUN useradd --uid 1000 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin processor
USER 1000

ENTRYPOINT ["python3", "-m", "processor.main"]
