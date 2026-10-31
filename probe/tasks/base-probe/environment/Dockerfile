FROM assay-probe-base:1@sha256:44c3dcbe182f91054aaa7c0d0eca335cbccc0d75883155820be1c4989b226cb6

# The seed repository: the stub and go.mod, committed once as `seed`.
WORKDIR /app
COPY seed/ /app/
RUN git init -q -b main \
 && git add -A \
 && git -c user.name=Assay -c user.email=assay@invalid commit -q -m seed \
 && go build ./... \
 && go vet ./...
