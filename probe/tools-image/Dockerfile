# Throwaway tools image for the image-mount probe (wayfinder ticket 55).
FROM golang:1.27.3-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5 AS build
WORKDIR /src
COPY main.go .
RUN go mod init probe && CGO_ENABLED=0 go build -o /out/bin/assay-probe-tool .

FROM scratch
COPY --from=build /out/ /
