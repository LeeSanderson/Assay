# How environment tools reach a trial under Harbor 0.24

Research for issue #46 (map #44). Question: how can **environment tools** (CLI tools available to the agent, such as `semgrep`, `gh` or a linter) reach a trial without installing the same tools in every job?

Sources: the pinned Harbor at `.venv/Lib/site-packages/harbor/` (Harbor 0.24, from `uv.lock`), the packs under `tasks/`, `instruments/agent.py`, ADR 0001, `PRD.md` "Task packs", the two local trial results under `results/` (phase0-smoke, phase0-local), and read-only/throwaway Docker commands on the dev machine (Docker Engine 29.5.3, Compose v5.3.1). Each claim names its source. "Unconfirmed" marks what was not checked.

## Short answer

The premise "every job installs the tools" is weaker than it looks. Harbor builds the pack image per trial, but the build is a cache hit: the observed `environment_setup` phase takes about 5.5 s. A `RUN` line in a Dockerfile is paid once per machine, not once per job. The per-trial cost today is the **agent setup** (42 to 54 s), which is mostly the Claude Code download.

The real constraint is a different one: a tool that is part of a **variant** must not be in the pack image, because the pack is shared by every condition, including the control. So:

- **Tools common to every condition** (the harness-neutral environment): put them in the image, either in the pack Dockerfile or in a digest-pinned shared Assay base image. Cost: one cached build.
- **Tools that belong to a variant**: add them at job level, because each condition is already its own job. The best fit is `environment.mounts` with `type: image` (a digest-pinned tools image mounted read-only). Fallback: upload static binaries in `setup()`, as the instruments already do with `jq`.

## 1. How Harbor gets the image (Docker environment)

- **Build or prebuilt.** If `[environment].docker_image` is set in `task.toml`, Harbor uses it as a prebuilt image, unless `force_build` is set and a Dockerfile exists. Otherwise it runs `docker compose build` on `environment/` (`environments/definition.py` `should_use_prebuilt_docker_image`; `environments/docker/docker.py` `start()`).
- **Compose files.** The build path uses `docker-compose-build.yaml`: `build.context: ${CONTEXT_DIR}`, `pull_policy: build`, and no `image:` key. The prebuilt path uses `docker-compose-prebuilt.yaml`: `image: ${PREBUILT_IMAGE_NAME}` (`environments/docker/`).
- **Image name per trial.** The compose project name is the trial's session id, `<trial_name>__env` (`trial/trial.py`, `session_id=f"{self.config.trial_name}__env"`; `docker.py` `_run_docker_compose_command`). With no `image:` key, Compose names the built image `<project>-main`. Seen on this machine: `split-second-stopwatch__gzgrfbh__env-main:latest` (`docker images`). Harbor also computes a content-addressed name `hb__<environment_id>` (`docker.py` line 274) with a comment that it lets unchanged content reuse the cached image, but the local Docker build compose file does not use `MAIN_IMAGE_NAME`; only `_validate_image_os` looks for it, and the smoke trial's log shows `Skipping image OS validation for hb__4b12b72995e905206375a7fcc68365aa: docker inspect returned 1` (`results/phase0-smoke/job.log`). So in 0.24 the content-addressed tag is dead code for local Docker.
- **Build serialisation.** Concurrent trials of the same task wait on a class-level lock, so only one builds and the others get the cache (`docker.py` `_image_build_locks`).
- **Deletion.** `stop(delete=True)` runs `docker compose down --rmi local --volumes --remove-orphans` (`docker.py` `stop()`). `delete` defaults to `true` (`models/trial/config.py` `EnvironmentConfig.delete`); `--no-delete` on `harbor run`/`harbor trials` (`cli/jobs.py`, `cli/trials.py`) or `environment.delete: false` in the job file keeps it; `keep_containers` only stops the containers. `--rmi local` removes only images with no custom tag from an `image:` key (Docker Compose documentation for `down --rmi`; consistent with the per-trial name above). So the per-trial image goes, but:
  - the **base images** (`FROM node@sha256:…`, `FROM golang@sha256:…`) stay; they are on this machine as `node:<none> 63538dfe497c` and `golang:<none> 972b4110ba0f` (`docker images`);
  - the **BuildKit layer cache** stays (`docker buildx du`: 1.59 GB reclaimable on this machine);
  - a **prebuilt** image (`docker_image`) is never removed, because the prebuilt compose file sets `image:`.
- **Measured cost.** `environment_setup` = 5.35 s and 5.67 s; `agent_setup` = 54.4 s and 42.2 s (`results/phase0-local/.../result.json`, `results/phase0-smoke/.../result.json`, TypeScript pack). The environment phase includes the cached build, `compose up` and mount setup. The agent phase runs Claude Code's `install()` (`curl … bootstrap.sh | bash -s -- 2.1.308`), then the instruments upload and the seed snapshot (`results/phase0-smoke/.../trial.log`). That most of the 42 to 54 s is the Claude Code download is an inference from the log's command order; the log has no per-command timestamps.
- **Cache eviction.** A cold build (cache pruned, `docker builder prune`, or BuildKit garbage collection) reruns every `RUN` line. The BuildKit GC limits on Docker Desktop were not checked (unconfirmed).

## 2. A shared Assay base image that packs start `FROM`

- **Mechanism.** Nothing in Harbor stops it: the pack Dockerfile is built as-is by Compose. A pack would say `FROM <registry>/assay-base-go@sha256:…` and carry the language toolchain plus the standard tools.
- **The digest rule.** `PRD.md` "Task packs", "The image": "A change of digest is a change of the task pack." If the pack Dockerfile pins the Assay base by digest, a new base is a new Dockerfile line, so the rule still holds and `task.toml` `[metadata].base_image` records it. If it pins only by tag, the base can change under a pack without any pack change, which breaks the rule. So: digest-pinned only.
- **Where the base lives.** `FROM name@sha256:…` needs that manifest digest to resolve. A registry (for example GHCR) gives a stable digest and lets `assay replay` and other machines rebuild. A base that exists only in the local image store may or may not resolve by digest (Docker 29 uses the containerd image store, where local images have manifest digests); unconfirmed, not tested.
- **Replay.** `assay replay` rebuilds from the pack Dockerfile (`README.md`, `assay replay`). With a shared base it also needs that base image, so the registry is needed for replay to work after a cache clean or on another machine.
- **Rebuild coupling.** A change to the base changes every pack that pins it; that is a corpus-wide pack change (compare ADR 0001's rejected "baked into each task image" option: "a hook change rebuilds every image").
- **The confound.** Every condition of an experiment uses the same pack, so a tool in the base image is available to the control too. A base image is right only for tools that are not part of a variant.
- **Saving the Claude Code download.** Harbor's `ClaudeCode.install()` returns early when `claude --version` already matches the job's `version` (`agents/installed/claude_code.py` `_installed_claude_satisfies_version`). A base image with Claude Code pre-installed at the pinned version would skip most of the 42 to 54 s per trial. But it would bind the harness version into the pack, which the PRD keeps apart ("Version pins"), and it does not help other harnesses.

## 3. A per-toolset layer per variant

Each condition is already its own job (`jobs/phase0-cross-tdd.yaml`: "Harbor sets extra instructions per job, so the two conditions are two jobs"), and the job has one `environment` block (`models/job/config.py` line 425). So any job-level environment option is effectively per variant.

### 3a. `environment.mounts` with `type: image` (recommended to prototype)

- **Harbor support.** `environment.mounts` is a list of `ServiceVolumeConfig` with `type: "bind" | "volume" | "image"`, plus `read_only` and `image.subpath` (`models/trial/config.py` lines 41 to 52). "Additional mounts for the agent environment only." Harbor appends them to its own log mounts (`trial/trial.py` `_agent_env_mounts`) and writes them as-is into a compose override `services.main.volumes` (`environments/docker/__init__.py` `write_mounts_compose_file`). Only writable mount targets are `mkdir`/`chmod`-ed (`docker.py` `start()`).
- **Docker support, tested.** `docker run --mount type=image,…` and a Compose file with `volumes: [{type: image, source: curlimages/curl:latest, target: /opt/tools, read_only: true}]` both mounted the image's file tree on this machine. Docker prints "Image mount is an experimental feature" (Engine 29.5.3, Compose v5.3.1). Not tested end to end through `harbor run` (no job was run).
- **libc caveat, tested.** The mounted `curl` from an Alpine (musl) image did not run in a Debian (glibc) container: `sh: 1: /opt/tools/usr/bin/curl: not found`. The tools image must hold static binaries, or binaries built for Debian bookworm glibc, under one prefix (for example `/opt/assay-tools/bin`). Go-built CLIs such as `gh` are usually static; Python-based tools such as `semgrep` need a self-contained bundle (unconfirmed per tool).
- **PATH.** The agent must find the tools. Options: `environment.env` (`models/trial/config.py`; passed as `persistent_env` in `environments/factory.py`) setting a full `PATH`, or a `setup()` step that symlinks into `/usr/local/bin`. Not tested.
- **Provenance.** A mount `source` written as `…@sha256:…` puts the content digest into the job file and into `lock.json` (the lock records the trial's `environment` block: `results/phase0-smoke/lock.json`). This answers ADR 0001's objection to mounts ("the lock records no content digest") for this use.
- **Cost.** No install per trial and no rebuild of the pack image; the tools image is pulled once and stays (it is not built by Compose, so `--rmi local` leaves it).
- **Risks.** Experimental Docker feature; host needs Docker Engine 28+ (unconfirmed exact minimum); other Harbor environment types (cloud providers) may ignore mounts (`environments/base.py` docstring: "Subclasses that don't bind-mount (cloud providers) may ignore the list"). Mounts do not reach a separate verifier environment (`trial/trial.py` `check_trial_config`), which is fine because tools are for the agent.

### 3b. `environment.mounts` with `type: bind`

Same plumbing as 3a with a host directory as source. Works on any Docker version, but the host is Windows, so the directory must hold Linux binaries, and the digest is not in the job file (same objection as ADR 0001). Weaker than 3a.

### 3c. `environment.extra_docker_compose` overlay

Job-level "Additional Docker Compose overlays for the agent environment only" (`models/trial/config.py`), appended after the task's compose files (`docker.py` `_docker_compose_paths`). An overlay that only adds volumes is the same as 3a. An overlay that replaces `services.main.build` or sets `image:` to build a variant layer on top of the pack image is possible in Compose but fights Harbor: the build context is the pack's `environment/`, a custom `image:` tag stops `--rmi local` from cleaning up, and `assay replay` would not know about the layer. Not tested; not recommended.

### 3d. Install or upload in the agent's `setup()` per trial

- **Mechanism.** The ADR 0001 route: `InstrumentedClaudeCode.setup()` already uploads `instruments/` with `environment.upload_dir` and makes the bundled `jq` executable (`instruments/agent.py` `_upload_instruments`). The same route can upload a variant's tool bundle (static binaries), or run an install.
- **Upload cost.** The instruments upload plus seed snapshot is part of the 42 to 54 s agent setup, and is small next to the Claude Code download (inference from the log, no timestamps). A tool bundle of a few tens of MB through `upload_dir` (`docker compose cp`, with a tar fallback, `environments/docker/docker_unix.py`) is likely seconds (estimate, not measured).
- **Install cost.** `apt-get update && apt-get install -y …` (how Harbor's own `ensure_system_dependencies` installs, `agents/installed/base.py`) or `pip`/`npm` installs need the network, take roughly 10 to 60 s per trial depending on the tools (estimate, not measured), and give unpinned versions unless pinned in the command. Multiplied by trials and repetitions this is the cost the map wants to avoid.
- **Provenance.** The tool bundle needs its own digest in the trial record, like `instruments.json`.

## Comparison

| Option | Per-trial cost | Pack changes? | Variant-specific? | Provenance | Main risk |
|---|---|---|---|---|---|
| Tools in pack Dockerfile | ~0 (cached build) | Yes, per pack | No (control sees them) | Dockerfile in pack | Confound; edits every pack |
| Shared Assay base (`FROM …@sha256`) | ~0 (cached build) | One `FROM` line per pack | No | Base digest in Dockerfile | Needs a registry; corpus-wide rebuild on change |
| `mounts` `type: image` | ~0 (one pull) | No | Yes (per job) | Digest in job file and lock | Experimental Docker feature; static binaries only |
| `mounts` `type: bind` | ~0 | No | Yes | None in lock | Host path; Linux binaries on Windows host |
| `extra_docker_compose` build layer | One build per variant × pack | No | Yes | Overlay file | Fights Harbor build/cleanup and replay |
| `setup()` upload of static bundle | Seconds (estimate) | No | Yes | Own digest (like `instruments.json`) | Coupled to Harbor internals (ADR 0001) |
| `setup()` install (apt/pip/npm) | ~10 to 60 s (estimate) | No | Yes | Weak unless pinned | Network, time, drift |

## Open points

- Does `FROM local-image@sha256:…` resolve without a registry on Docker 29's containerd store? (untested)
- Does an `image`-type mount work end to end through `harbor run` (Harbor's compose override plus `ensure_dirs`)? A free `oracle`/`nop` agent trial would show it without model cost.
- Which candidate tools (`semgrep`, `gh`, linters) exist as static or bookworm-compatible bundles?
- BuildKit GC limits on Docker Desktop, so how often a "cached" pack build is in fact cold.
