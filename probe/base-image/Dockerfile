# Throwaway shared Assay base for the probe: the Go pack base plus the tools image.
FROM golang:1.27.3-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5
COPY --from=assay-probe-tools:1@sha256:154130487dde586beeee9f7d2cc3723a0ead9e8c4abcf85e68eee370a801c3ad /bin/assay-probe-tool /usr/local/bin/
