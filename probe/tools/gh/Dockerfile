# Probe (wayfinder ticket 57): a tools image built from tools.lock.
# The tree is built at /opt/assay-tools and copied to the image root, because
# the job file mounts the image at /opt/assay-tools.
FROM golang:1.27.3-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5 AS fetch
COPY tools.lock /lock/
RUN set -eu; mkdir -p /dl /opt/assay-tools/bin; \
    grep -v '^#' /lock/tools.lock | while read -r sha url; do \
      f="/dl/$(basename "$url")"; curl -fsSL -o "$f" "$url"; echo "$sha  $f" | sha256sum -c -; \
    done; \
    tar -xzf /dl/gh_2.103.3_linux_amd64.tar.gz -C /dl; \
    cp /dl/gh_2.103.3_linux_amd64/bin/gh /opt/assay-tools/bin/gh

FROM scratch
COPY --from=fetch /opt/assay-tools /
