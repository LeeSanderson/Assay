# Which route delivers a variant's environment tools

Research for issue #56 (map #44). Question: which route puts a variant's **environment tools** into a trial: (A) a mounted tools image, (B) a per-variant image or layer, or (C) installation at run time?

Settled rules that this note does not reopen (#51): tools are a variant part (`differs_in = "tools"`). The control gets no variant tools. Every trial records a content digest of its tools, and a route that cannot give one is ruled out. Assay adds no text about tools. Experiments reference committed job files and never generate them.

Prior results used here: #46 (`docs/research/environment-tools.md` on `research/environment-tools`) and #55 (an image mount works through `harbor run`, and `lock.json` keeps the digest-pinned mount entry).

**Sources.** The pinned Harbor 0.24 package at `.venv/Lib/site-packages/harbor/`, Docker documentation and release notes, the GitHub release pages and PyPI files of each tool, and throwaway local experiments with no model cost. The test machine: Docker Engine 29.5.3 (containerd image store), Compose v5.3.1, Buildx v0.35.0. Each claim names its source. "Measured" means a local run on this machine. "Not tested" marks a claim with no local check.

## Short answer

**Recommendation (the human decides): route A, a digest-pinned tools image mounted read-only.** It is the only route that meets all the settled rules with no new record and no per-trial cost. The control's container comes from the same image build as the variant's container. The digest is in the committed job file and in each trial's `lock.json`. Replay on another machine needs the same tools image, which comes from a `docker save` archive or a registry.

Route B is possible only through a Compose overlay. That overlay fails Harbor's `up --wait`, gives no digest in the lock, and adds about 6 to 8 s of build time to each trial. Route C costs about 4.5 s (static binaries) to about 38 s (`semgrep`) per trial, needs the network, and changes system packages, not only tools.

## 1. What each route is under Harbor 0.24

- **A. Mounted tools image.** The job file has an `environment.mounts` entry with `type: image`. Harbor writes the list unchanged into a Compose override (`environments/docker/__init__.py` `write_mounts_compose_file`), and the mount reaches the agent environment only (`models/trial/config.py` `EnvironmentConfig.mounts`: "Additional mounts for the agent environment only"). Docker added `--mount type=image` and the `image-subpath` option in Engine 28.0.0 (Docker Engine 28 release notes). The Compose file reference lists `image` as a mount type, and `image.subpath` needs Compose 2.35.0 (Compose file reference, "services", `volumes`). Docker logs "Image mount is an experimental feature" (measured, and #55).
- **B. Per-variant image or layer.** Harbor has no job-level option that changes the task's image. `EnvironmentConfig` has `force_build`, resource overrides, `mounts`, `extra_docker_compose`, `env` and `kwargs`, but no image or Dockerfile override (`models/trial/config.py`). The image comes from `task.toml` `[environment].docker_image` or from the pack's `environment/` (`environments/docker/docker.py` `start()`). So B has two forms:
  - **B1. A copy of each pack per variant**, with a Dockerfile that adds the tools. The control and the variant then run different task packs. Under PRD "Task packs", a change of the image is a change of the pack, so a comparison across conditions is no longer on the same pack. Ruled out on that ground; not tested.
  - **B2. A Compose overlay** in `environment.extra_docker_compose` that replaces the main service's build with a layer on top of the pack. Tested; see section 2.
- **C. Installation at run time.** The agent class's `setup()` downloads or installs the tools, as ADR 0001's route already uploads `jq`. The pack's `network_mode = "public"` (`tasks/*/split-second-stopwatch/task.toml`) lets it reach the network.

## 2. Cost per trial and cache behaviour

All measured on this machine, three runs each unless stated.

| Route | Measured cost per trial | Cache behaviour |
|---|---|---|
| Pack build today (no tools) | 0.82 to 0.86 s for a cached `docker compose build` of the Go pack | BuildKit cache survives `down --rmi local` (#46) |
| A. Image mount | Container start 0.63 to 0.71 s with the mount, 0.59 to 0.62 s without: about 0.05 s more | The tools image is not built by Compose, so `down --rmi local` keeps it. It is built once per machine. |
| B2. Compose overlay layer | 6.4 to 8.6 s for the cached build (pack plus a 218 MB `COPY` of the tools), against 0.8 s for the pack alone. First build: 28.8 s. | Each trial removes the image (`down --rmi local`), and the next trial copies the tools layer again. |
| C. Run-time download of static binaries (`gh`, `golangci-lint`) | 4.5 s, with container start | None: each trial downloads again. |
| C. Run-time install of `semgrep` in the Go pack | 4.8 s for `apt-get install python3-venv`, then 33.0 s for `pip install semgrep==1.183.0`; one run | None. The Go image has `python3` but no `pip` and no `venv` module, so the install also needs `apt`. |

Source for B2's behaviour: a throwaway Compose project in the scratchpad, with Harbor's `docker-compose-build.yaml` and an overlay. The B2 image ID changed on each rebuild from cache (`b098e044…` then `579a71ac…`), so the built image has no stable digest to record.

## 3. What each route pins, and how a digest gets into the record

- **A.** The mount `source` is `name:tag@sha256:<digest>`. `lock.json` records the whole mount entry with the full digest (#55). With the containerd image store, a local image's ID is the manifest digest, and `RepoDigests` lists `name@sha256:<id>` with no push (measured: `assay-research-tools@sha256:a2330245…`). The digest covers the whole content of the tools image. Harbor does not resolve a tag to a digest, so the plan step must reject a mount source with no `@sha256:` (#55). As an option, the recorder can also hash the mounted tree into `instruments.json`, as it does for the instruction file. Measured: 2.2 s for 9,154 files (677 MB, mostly `semgrep` and its Python). This is not needed for the rule, because the lock already holds the digest.
- **B2.** `extra_docker_compose` is a list of file paths (`models/trial/config.py`), so the lock records the overlay's path and not its content, the same gap that PRD "Settings" names for a settings file path. The tools image digest is in the overlay file, not in the lock, and the built image changes digest on each build (section 2). B2 needs a separate record, such as an `instruments.json` entry. Ruled out as the primary route.
- **C.** A download can pin each file with a checksum (`gh` and `staticcheck` publish `.sha256` files; release pages in section 6). `pip` and `apt` resolve dependencies at run time, so the installed tree can differ between trials unless every package is pinned with hashes. The recorder must hash the installed tree after setup to give a content digest. That hash proves what the trial had, but two trials of one variant can have different digests, which breaks the bundle-identity rule for `differs_in = "tools"`.

## 4. Is the control's image the same as the variant's, apart from the tools?

- **A. Yes.** Both conditions build the same pack, so they get the same image. The variant's container adds only a read-only mount at the target directory. Writes to the mount fail with "Read-only file system" (#55). One more difference: the tools must be on `PATH` (section 7).
- **B2. No, in part.** The pack layers are the same, but the variant runs a different image with one more layer, and B2 also starts a second service (section 5).
- **C. No.** The install writes into the container's writable layer. `apt-get install python3-venv` also adds system packages that are not variant tools, so the variant's container differs in more than the tools.

## 5. Replay on another machine, and whether a registry is needed

- **A.** `assay replay` runs only the pack image (PRD "Replay of the trace snapshots": "It needs the images of the task packs only"), so replay does not need the tools image. A new trial on another machine does. A `--no-cache` rebuild of the same tools Dockerfile gave a different digest (measured: `d066a3fe…` then `d5a472cd…`), so the Dockerfile alone does not reproduce the pinned digest. Two ways keep the digest: `docker save` and `docker load` kept the image ID unchanged (measured), or a push to a registry such as GHCR. That a GHCR push keeps the local manifest digest is not tested. On one machine, no registry is needed (#55: `name:tag@sha256:` resolves locally).
- **B2.** Same need for the tools image. In addition, the overlay fails at start (next point).
- **C.** Needs the network and the upstream files at trial time. A removed release or a changed package index stops the trial or changes it.

**B2 fails Harbor's start.** The only way found to layer on top of the pack inside one Compose project is a helper service that builds the pack, referenced as `additional_contexts: {pack: "service:pack"}`, with `dockerfile_inline: "FROM pack\nCOPY --from=tools …"`. A helper in a Compose profile is hidden from the build ("service main declares unknown service pack as additional contexts"). Without a profile, `up` starts the helper too. Harbor runs `up --detach --wait` (`environments/docker/runtime.py` `up_args`), and that command exited with code 1 because the helper container exited. A helper that sleeps forever would avoid that, but it is a second container in every trial. All measured.

## 6. Which candidate tools run in the bookworm packs

Both pack images run Debian GLIBC 2.36 (`ldd --version`, measured). Each tool was put into one tools image (`FROM scratch`, with all files under `/opt/assay-tools`), mounted into the digest-pinned Go and Node pack base images, and run with `--version`. `file` gives the link type.

| Tool | Release asset | Link type | Go pack | Node pack |
|---|---|---|---|---|
| `gh` 2.103.3 | `gh_2.103.3_linux_amd64.tar.gz` (cli/cli releases) | static (Go) | runs | runs |
| `golangci-lint` 2.15.0 | `golangci-lint-2.15.0-linux-amd64.tar.gz` (golangci/golangci-lint releases) | static (Go) | runs | runs |
| `staticcheck` 2026.2.2 | `staticcheck_linux_amd64.tar.gz` (dominikh/go-tools releases) | static (Go) | runs | runs |
| `shellcheck` 0.11.0 | `shellcheck-v0.11.0.linux.x86_64.tar.xz` (koalaman/shellcheck releases) | static | runs | runs |
| `ruff` 0.17.3 | `ruff-x86_64-unknown-linux-gnu.tar.gz` (astral-sh/ruff releases) | dynamic, glibc | runs | runs |
| `biome` 2.6.4 | `biome-linux-x64` (biomejs/biome releases) | dynamic, glibc | runs | runs |
| `semgrep` 1.183.0 | PyPI wheel `…-manylinux_2_34_x86_64.whl` (needs glibc 2.34 or later; Python 3.10 or later), installed into a python-build-standalone CPython 3.11.18 (`…-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz`) under `/opt/assay-tools/python` | Python script; `semgrep-core` is dynamic, glibc | runs, and an offline scan with a local rule (`--network none`, `--metrics=off`) found the match in 1.4 s | runs |
| `eslint` 10.14.0 | npm package, installed with `npm install -g --prefix /opt/assay-tools` | needs `node` | fails: `/usr/bin/env: 'node': No such file or directory` | runs |

Facts from this:

- **Go CLIs and ShellCheck are static.** They run in any Linux container.
- **musl is a problem only when the binary links musl dynamically.** The Alpine `curl` that failed in #46 is dynamic. Ruff and Biome also publish `…-musl` builds, which are usually static; not tested.
- **semgrep has no standalone binary.** Its GitHub release has no Linux assets; it ships as PyPI wheels only. A self-contained bundle needs its own Python. pip writes the absolute interpreter path into the `semgrep` script, so the mount target must be the same path as the build path (`/opt/assay-tools`).
- **Node tools (`eslint`) need `node`.** The TypeScript pack has it; the Go pack does not. A Node tool for Go packs needs a Node runtime in the tools image. ESLint and the Yarn PnP seed (`tasks/typescript/*/environment/Dockerfile`) were not tested together.
- **Size.** The image with all the tools except ESLint is 218 MB compressed and 677 MB on disk; most of it is `semgrep` and its Python.

## 7. How the job file expresses route A, and the `variants.toml` field

**PATH.** The tools are not on `PATH` after the mount. `environment.env` is not a good way to add them, for two reasons. First, Harbor writes the value into the Compose override and into each `docker compose exec -e` with no escape (`environments/base.py` `_startup_env`, `_merge_env`; `environments/docker/__init__.py` `write_env_compose_file`), so `${PATH}` would take the host's `PATH`. Second, a full literal `PATH` is different for each pack: Go is `/go/bin:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:…`, Node is `/usr/local/sbin:/usr/local/bin:…` (`docker image inspect`, measured), and one job runs both packs. Harbor runs commands with `bash -c`, not a login shell (`environments/docker/docker_unix.py` `exec_shell_args`), so a profile script has no effect. The workable way: Assay's agent class, in `setup()`, links each file in `<target>/bin` into `/usr/local/bin`, which is on `PATH` in both images. This is variant delivery, like the instruction file upload (#51 point 5). Not tested through `harbor run`.

**Job file (variant job only):**

```yaml
environment:
  mounts:
    - type: image
      source: assay-tools-semgrep:1@sha256:<64 hex>
      target: /opt/assay-tools
      read_only: true
```

If the tools image holds the tree at its root (`COPY --from=fetch /opt/assay-tools /`), no `image.subpath` is needed, and Compose 2.35 is not a requirement. The control's job file has no tools mount.

**Plan-time checks for `assay experiment`**, the same pattern as `kwargs.instruction_file` (#51 point 5):

1. Each job's tools mount `source` equals the manifest's `tools` value for the job's condition, character for character, and has `@sha256:`.
2. A control job has no mount at the tools target.
3. `docker image inspect <source>` succeeds before the job starts, because a missing image gives a `RuntimeError` at environment start that a rerun cannot fix (#55).

**Recommended `variants.toml` shape (a recommendation; the human decides):**

```toml
[semgrep-rules]
label = "…"
tools = "assay-tools-semgrep:1@sha256:<64 hex>"   # digest-pinned tools image, mounted read-only at /opt/assay-tools
```

- `tools` is one image reference in the form `name:tag@sha256:<digest>`. The digest is the identity of the tools part, so two variants have the same tools when the two strings have the same digest. `differs_in = "tools"` passes when only this value differs.
- The mount target is fixed by Assay (`/opt/assay-tools`), not a manifest field. A different target would be a different treatment with no purpose.
- The Dockerfile that built the image can sit at `variants/<name>/tools/Dockerfile` for people to read. It is not the record, because a rebuild gives a new digest (section 5). The image archive (`docker save`) or a registry copy is what replay on another machine needs.

## 8. Comparison

| Point | A. Mounted tools image | B. Per-variant image or layer | C. Install at run time |
|---|---|---|---|
| Cost per trial | about 0.05 s (measured) | B2: 6 to 8 s cached build (measured); B1: not tested | 4.5 s (static binaries) to 38 s (`semgrep`), measured |
| Cache | Built once per machine; Harbor's cleanup keeps it | Layer copied again each trial | None |
| Digest in the record | Yes: in the job file and `lock.json` | B2: no (path only in lock; image digest changes per build) | Only by hashing after install; varies between trials |
| Control's image the same | Yes, plus a read-only mount | B1: different pack; B2: extra layer and a helper service | No: writable layer and extra system packages |
| Replay on another machine | Needs the tools image: `docker save` archive or registry | Same, and B2 fails `up --wait` | Needs the network and upstream files |
| Job file | One `environment.mounts` entry | B1: a pack copy per variant; B2: an overlay file | Agent kwargs |
| Main risk | Docker calls image mounts experimental; needs Engine 28 or later | Fights Harbor's build, start and cleanup | Time, network, drift |

## Open points

- The `setup()` link step into `/usr/local/bin` is not tested through `harbor run`. The verifier shares the container, so the links are on `PATH` for `tests/test.sh` too (#55).
- Whether a GHCR push keeps the local manifest digest is not tested.
- Whether Claude Code's Bash tool keeps the container `PATH` is assumed from Harbor's `bash -c` exec, not tested.
- `gh` needs a token and the network for most commands; that is a variant design question, not a route question.
- The throwaway images `assay-research-tools:1`, `assay-research-eslint:1` and `assay-research-eslint:rebuild` are in the local image store and can be deleted.
