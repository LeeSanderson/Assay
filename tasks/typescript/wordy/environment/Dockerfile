FROM node:22.23.4-bookworm@sha256:63538dfe497cc29dfafdda25ada09b46db68a3f4cc205abf1f5d6bf0913f3384

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /app

COPY seed/ /app/

# The seed repository: one commit, `seed`, holding the seed files only.
# Fixed identity and dates keep the commit hash the same on every build.
RUN git init -q -b main \
 && git add -A \
 && GIT_AUTHOR_DATE="2000-01-01T00:00:00Z" GIT_COMMITTER_DATE="2000-01-01T00:00:00Z" \
    git -c user.name=assay -c user.email=assay@localhost commit -q -m seed

# Install the dependencies (Yarn PnP, global cache under /root/.yarn) and keep
# yarn itself in the corepack cache, so the tests run with no network.
# The install files stay out of git status through .git/info/exclude.
RUN corepack yarn install --immutable \
 && printf '.pnp.*\n.yarn/\n' >> .git/info/exclude \
 && test -z "$(git status --porcelain)"
