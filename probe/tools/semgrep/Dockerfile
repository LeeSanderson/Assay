# Probe (wayfinder ticket 57): the semgrep bundle built from tools.lock and
# requirements.txt. pip writes the interpreter's absolute path into the
# `semgrep` script, so the build path is the mount target, /opt/assay-tools.
# PIP_FLAGS lets a second build try pip options that make the tree reproducible.
FROM golang:1.27.3-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5 AS fetch
ARG PIP_FLAGS=""
ARG SOURCE_DATE_EPOCH=""
COPY tools.lock requirements.txt /lock/
RUN set -eu; mkdir -p /dl /opt/assay-tools/bin; \
    grep -v '^#' /lock/tools.lock | while read -r sha url; do \
      f="/dl/$(basename "$url")"; curl -fsSL -o "$f" "$url"; echo "$sha  $f" | sha256sum -c -; \
    done; \
    tar -xzf /dl/cpython-*.tar.gz -C /opt/assay-tools; \
    if [ -n "$SOURCE_DATE_EPOCH" ]; then export SOURCE_DATE_EPOCH; fi; \
    /opt/assay-tools/python/bin/python3 -m pip install --no-cache-dir --disable-pip-version-check \
      --require-hashes --only-binary :all: $PIP_FLAGS -r /lock/requirements.txt; \
    ln -s ../python/bin/semgrep /opt/assay-tools/bin/semgrep

FROM scratch
COPY --from=fetch /opt/assay-tools /
