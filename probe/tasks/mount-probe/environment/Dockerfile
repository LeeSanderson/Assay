FROM golang:1.27.3-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5

# The seed repository: the stub and go.mod, committed once as `seed`.
WORKDIR /app
COPY seed/ /app/
RUN git init -q -b main \
 && git add -A \
 && git -c user.name=Assay -c user.email=assay@invalid commit -q -m seed \
 && go build ./... \
 && go vet ./...
