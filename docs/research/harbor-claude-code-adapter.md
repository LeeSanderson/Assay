# What the current Harbor does for the `claude-code` adapter

Research for [issue #2](https://github.com/LeeSanderson/Assay/issues/2), part of the Phase 0 map ([issue #1](https://github.com/LeeSanderson/Assay/issues/1)).
Date: 2026-10-18.

## Sources and trust

- **Harbor source, primary.** Repo [`harbor-framework/harbor`](https://github.com/harbor-framework/harbor) (the old `laude-institute/harbor` URL redirects here). Read at tag **`v0.24.0`**, commit `b53b8134e1241686dca7759af188f987ecc48e8b`, released 2026-10-05. Below, `src/...` means `https://github.com/harbor-framework/harbor/blob/v0.24.0/src/...`. Where the docs and the source disagree, this note follows the source.
- **Harbor docs.** The `docs-mintlify/` tree in the same tag, which is published at docs.harborframework.com.
- **Claude Code docs.** [CLI reference](https://code.claude.com/docs/en/cli-reference), [settings](https://code.claude.com/docs/en/settings), [hooks](https://code.claude.com/docs/en/hooks).
- **Claude Code session logs, observed.** Local `~/.claude/projects/**/*.jsonl` transcripts written by Claude Code 2.1.278 to 2.1.301 on Windows. They show the shape of `toolUseResult`, which Harbor converts. This is direct evidence about the input format, but it was not taken from a Harbor run inside Linux.

Nothing here was checked by running Harbor. Every "confirmed" below means confirmed by reading code or docs. Phase 0 still has to run it.

## Verdict on PRD claims (summary)

| PRD claim | Verdict |
|---|---|
| `--skill` uploads to `/harbor/skills/<name>/` | **Confirmed** |
| …"and it keeps the execute bit" | **Partly.** `docker compose cp` keeps the host mode, and Harbor's `chmod -R a+rX` adds no `x` to files. The bit survives only if the host file already has it. |
| Lock records name, source, digest per skill | **Confirmed**, and git URL and commit as well. The digest covers paths and contents, **not modes**. |
| Duplicate skill names: last wins, no error | **Confirmed** |
| `--ak config=<path or JSON>`: uploaded and passed via `--settings` | **Confirmed**, with caveats: Harbor re-serializes the JSON (same content, different bytes), and the content of a config *file* is not recorded in the lock |
| A `hooks` key in that settings object fires | **Not verified.** Claude Code docs say `--settings` keys override the file keys, but no doc names `--settings` as a hook source. Phase 0 must test it (as Risk 8 already plans). |
| `/logs/artifacts` collected into the trial tree | **Confirmed, at a different path:** `<trial>/artifacts/logs/artifacts/`, not `<trial>/artifacts/` |
| Bash exit code "under `extra.tool_result_metadata`" | **Contradicted.** Claude Code writes no exit-code field for a successful Bash call. For a failed call, `toolUseResult` is the string `"Error: Exit code N\n…"`, and Harbor does not parse it. See §5. |
| `Write`/`Edit`/`Bash` arguments verbatim | **Confirmed** |
| `Skill` call appears as a tool call with that name | **Confirmed** (`function_name: "Skill"`, `arguments: {"skill": "<name>"}`) |
| "One step holds every tool call of one agent turn" | **Confirmed if "turn" means one LLM response** (one `message.id`). Timestamp is the first event of that response. |
| Flags `--base-url`, `--api-key-name`, `--api-format`, `--skip-model-parsing-and-provider-mapping` | **Contradicted.** None of them exist in v0.24.0. |
| `agent-auth-resolution.mdx` documents it | **Contradicted.** There is no such page in v0.24.0. |
| `examples/configs/features/ollama-job.yaml` is a working local example | **Exists, but not for this adapter.** It uses `terminus-2` through LiteLLM, not `claude-code`. |
| PRD YAML: `base_url`, `api_format`, `timeout_multiplier` on the agent entry | **Contradicted.** `AgentConfig` has none of these fields. They are dropped without a message (pydantic default). `timeout_multiplier` is a job-level key. |
| PRD YAML: `kwargs.model_info` for `claude-code` | **Contradicted.** `ClaudeCodeOptions` forbids unknown kwargs, so preflight rejects the job. |
| L5: Harbor records `None` cost for a local model | **Not verified, probably wrong** for `claude-code`. Cost comes from Claude Code's own `total_cost_usd`. |
| `concurrency_group` + `n_concurrent` on the agent | **Confirmed** |
| Default task network mode is `public` | **Confirmed** |
| L7: a service with explicit `network_mode`/`networks` is not routed through the egress sidecar | **Confirmed.** There is an extra catch for `extra_hosts`, see §7. |
| "Terminal recording only from Terminus-2" | Not checked (out of scope) |

---

## 1. Version, install and pin, Docker

- **Current version:** `0.24.0` (`pyproject.toml`), released 2026-10-05. The releases before it were 0.23.0 (2026-09-12) and 0.22.0 (2026-08-22). Harbor releases about every three weeks, and the `CHANGELOG.md` lists many **Breaking** entries, so pinning matters.
- **Python:** `requires-python = ">=3.12"`.
- **Install** (`docs-mintlify/getting-started/installation.mdx`): `uv tool install harbor` or `pip install harbor`. To pin on WSL2 Ubuntu or Linux, run `uv tool install harbor==0.24.0` (uv fetches Python 3.12 if needed). The CLI entry points are `harbor` and `hr`. Nightly dev builds also exist (`--prerelease explicit 'harbor>=0.dev0'`); do not use them.
- **Pin Claude Code inside the container too:** `--ak version=<x.y.z>`. `install()` passes it to the bootstrap script (`curl … bootstrap.sh | bash -s -- <version>`), and it skips the install if `claude --version` already matches (`src/harbor/agents/installed/claude_code.py` L451–491). Without this kwarg, every trial installs the **latest** Claude Code. That is a version confound across a long matrix.
- **Docker:** the default sandbox is local Docker. The runtime calls the `docker` engine CLI and `docker compose` (Compose V2) (`src/harbor/environments/docker/runtime.py` L46). Podman is an alternative (`-e podman`). The egress sidecar is used only for `allowlist`/`no-network` modes. It needs Linux containers and nftables kernel support (`docs-mintlify/tasks/network-policies.mdx`, footnote 4).
- **Rancher Desktop:** neither the source nor the docs mention it. Harbor needs a `docker` CLI with the `compose` plugin, so Rancher Desktop must use the **dockerd (moby)** engine, not containerd/nerdctl. *Not verified by a run.*
- **Windows host caveats from the source:** on a Windows host, `fcntl` locking of the skill cache is skipped (`src/harbor/skills.py` L190–211). `upload_dir` also runs `sed -i 's/\r$//'` on `*.sh`/`*.py` (`src/harbor/environments/docker/docker_unix.py` L163–177). Run Harbor **inside WSL2**, with the repo on the WSL ext4 filesystem, not `/mnt/c`, so that Linux file modes are real.

## 2. `--skill`: location, execute bit, lock

- **Where skills land.** Each skill directory is uploaded to `/harbor/skills/<name>/`, where `<name>` is the directory basename (`EnvironmentPaths.default_skills_dir`, `src/harbor/models/trial/paths.py` L46; `Trial._upload_injected_skills`, `src/harbor/trial/trial.py` L1653–1678). A task that declares `environment.skills_dir` changes this path (L1636–1651). The upload happens after the environment healthcheck and before agent setup (`docs-mintlify/jobs/skills.mdx`).
- **Then the adapter copies them.** `claude-code` runs `cp -r /harbor/skills/* $CLAUDE_CONFIG_DIR/skills/` (`claude_code.py` L1688–1700), where `CLAUDE_CONFIG_DIR=/logs/agent/sessions` (L1895). Before that, it also copies any `~/.claude/skills` already in the **task image** into the same place (L1897–1903). Task images must therefore ship no `~/.claude/skills`, or that skill leaks into the control condition.
- **The source copy stays.** `/harbor/skills/<name>/` remains on disk for the whole trial, so a hook can call an absolute path under it. The PRD's "Where hook scripts live" route is valid.
- **Execute bit.** The upload is `docker compose cp <src>/. main:<dst>`, with a tar fallback (`docker_unix.py` L153–162). This copy keeps file modes. After it, Harbor runs `chmod -R a+rX` (`trial.py` L1670–1678). Capital `X` adds execute only to directories and to files that are already executable, so it **adds no `x` to a plain file**. `cp -r` without `-p` keeps the mode, less the umask. Result: the bit survives only if the host file has it. On WSL ext4 with a git checkout, that requires the file to be committed with mode `100755` (`git update-index --chmod=+x`). The safest hook command is `bash /harbor/skills/<name>/hook.sh`, which needs no execute bit.
- **Lock.** Each trial's `lock.json` (`TrialLock.skills`) and the job lock hold one `AgentSkillLock` per resolved skill: `name`, `source` (resolved host path), `digest`, `git_url`, `git_commit_id` (the last two only for git sources) (`src/harbor/models/job/lock.py` L143–162, L562–574). `digest` is `sha256:` over the sorted `(relative_path, sha256(content))` pairs (`compute_skill_digest`, `src/harbor/skills.py` L214–223). **File modes are not in the digest**, so a lost execute bit does not change it.
- **Duplicates and directory roots.** `resolve_skills` keys skills by directory name: the last one wins, with no warning, and the result is sorted by name (`skills.py` L125–137). A `--skill` path that contains no `SKILL.md` is a root, and each child directory must contain `SKILL.md`. Otherwise the job raises an error (L394–428). This confirms the PRD comparability rule about unique names.

## 3. `--ak config=<path or JSON>`, `--settings`, and hooks

- **Parsing.** `--ak key=value` values are parsed as JSON first, then as a Python literal, then kept as a string (`src/harbor/cli/utils.py` `parse_kwargs`). So `config={"hooks":{…}}` becomes a dict and `config=variants/gate/settings.json` becomes a path. Since the "options_model" change (`CHANGELOG.md`), **unknown kwargs fail at preflight**. Run `harbor agent schema claude-code` to list the accepted fields. For `claude-code` they are `version`, `prompt_template_path`, `config`, `max_turns`, `reasoning_effort`, `thinking_display`, `max_budget_usd`, `fallback_model`, `append_system_prompt`, `allowed_tools`, `disallowed_tools`, `disable_web_search`, `permission_mode` (default `bypassPermissions`), `max_thinking_tokens`, `memory_dir` (`claude_code.py` L53–109; `src/harbor/agents/options.py` L50–71).
- **Validation.** A dict must round-trip through JSON unchanged. A path must be an existing file (`src/harbor/agents/installed/base.py` L620–651). `ClaudeCode._load_base_settings` requires a JSON **object** (`claude_code.py` L377–397). Harbor does not inspect or filter any keys, so `hooks` passes through.
- **Upload and launch.** The object is written with `json.dumps(…, indent=2)` to `/tmp/claude-code-settings/settings.json`. Claude is then started as `claude --verbose --output-format=stream-json --settings /tmp/claude-code-settings/settings.json … --print` (L399–409, L1922–1963). The directory is deleted in a `finally` block after the run (L1964–1976). The content is semantically unchanged but **not byte-identical** (re-serialized). A hook must not read that file after the agent stops.
- **Lock gap.** For a *path* config, only the path is stored (inside `agent.kwargs` in `lock.json`/`config.json`). No digest of the file content is recorded. **Pass the settings inline (as a dict in the job YAML `kwargs.config`) so that the exact hook declaration is in every trial's `config.json`/`lock.json`.** Otherwise the analyzer cannot prove which hook ran.
- **Will `hooks` fire? Not verified.** The Claude Code docs say `--settings` is precedence level 2 ("Command line"): "A key you set there overrides the same key in your project and user settings files" ([settings](https://code.claude.com/docs/en/settings)). They also say "Hook entries merge across settings levels" ([hooks](https://code.claude.com/docs/en/hooks)). The hooks page lists hook locations as user, project, local, managed, plugin, and skill/agent frontmatter. It shows `--settings` only to *disable* hooks (`--settings '{"disableAllHooks": true}'`). The docs therefore suggest that hooks in `--settings` apply, but they never say so explicitly. Phase 0's marker-file trial is the right test.
- **Other sources that can add hooks.** `CLAUDE_CONFIG_DIR` points at `/logs/agent/sessions`, so no user-level `settings.json` exists unless the image creates one. A `.claude/settings.json` in the task's seed repo (cwd `/app`) **would** load and add hooks. Keep `.claude/` out of seed repos.
- **Hook event detail that matters for the trace hook.** `PostToolUse` "fire[s] after a tool has already executed successfully". Its input has `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, and `duration_ms` ([hooks](https://code.claude.com/docs/en/hooks)). A failed tool, such as a failing test run, goes to `PostToolUseFailure`, not `PostToolUse`. A trace hook that should record test runs must handle both events.

## 4. `/logs/artifacts`

- **Collected automatically.** Yes. On Docker, `/logs/artifacts` is a **bind mount**, so writes go straight to the host (`trial.py` L1918–1928). The artifact handler always adds an implicit "convention entry" for this directory and records it in `artifacts/manifest.json` with status `ok` or `empty` (`src/harbor/models/task/artifacts.py` L62–78; `src/harbor/trial/artifact_handler.py` L132–167, L270–285, L343–361). Non-mounted (cloud) environments download it instead.
- **Path differs from the PRD.** The host side is `host_artifact_path("main", "/logs/artifacts")` = **`<trial>/artifacts/logs/artifacts/`** (`trial.py` L1348–1353). The code comment says this is deliberate: "mounted at its own mirrored host location (artifacts/logs/artifacts/), not at the artifacts/ root". The `TrialPaths` docstring agrees (`paths.py` L95–107). The PRD diagram ("`artifacts/` files collected from /logs/artifacts") and the Phase 0 check ("the marker reaches the trial tree") must use this path.
- **Other trial-tree names, checked against `TrialPaths`:** `agent/` (holds `trajectory.json`, `claude-code.txt`, `sessions/`), `verifier/reward.json`, `config.json`, `lock.json`, `result.json`, `trial.log`. The docstring says `results.json`, but the code says `result.json` (`paths.py` L286–289).

## 5. ATIF output of `claude-code`

Conversion: `ClaudeCode._convert_events_to_trajectory` reads `agent/sessions/projects/*/<session>.jsonl` plus `subagents/*.jsonl` (`claude_code.py` L1124–1654). It writes `schema_version: "ATIF-v1.7"`.

- **Step granularity.** One ATIF step per **assistant `message.id`**, meaning one LLM inference. Its text, reasoning, and *all* its `tool_use` blocks are merged into that one step, even when the session log splits them across events (L1293–1368, citing "RFC-0001 (`step` == one turn)"). Tool results attach to the step that made the call, as `observation.results[]` matched by `source_call_id` (L1418–1440, L673–723). Plain user messages become their own `source: "user"` steps, and so does a skill body injected as a user text block. Events from all files are sorted by timestamp, and subagent steps carry `extra.is_sidechain` / `extra.agent_id` (L1171–1177).
- **Timestamp** is the timestamp of the *first* session event for that `message.id`, so it is per response, not per call (L1299–1311). Within a step, call order is array order. This confirms the PRD limit, with "turn" read as "one model response". Claude often makes one call per response, so most steps hold a single call.
- **Verbatim arguments.** `ToolCall.arguments` is the raw `tool_use.input` dict, unchanged. A copy also goes to `ToolCall.extra.raw_arguments` (L1343–1366). In practice: `Write` → `{"file_path", "content"}`; `Edit` → `{"file_path", "old_string", "new_string", "replace_all"}`; `Bash` → `{"command", "description", …}`. Confirmed against local Claude Code transcripts.
- **Exit code: PRD contradicted.** `_format_tool_result` (L929–999) looks for `exitCode`/`exit_code` in `toolUseResult` *only when it is a dict*. The real Claude Code transcripts show this:
  - successful Bash: `toolUseResult = {"stdout","stderr","interrupted","isImage","noOutputExpected", sometimes "returnCodeInterpretation"}`, with **no exit-code field**;
  - failed Bash: `tool_result.is_error = true`, `content = "Exit code 1\n<output>"`, and `toolUseResult` is the **string** `"Error: Exit code 1\n…"` (190 cases in 77 local transcripts, Claude Code 2.1.278+).

  In ATIF, a successful Bash call therefore has `observation.results[i].extra.tool_result_metadata.tool_use_result` (a dict with no exit code) and `tool_result_is_error: false`. A failed one has `extra.tool_result_is_error: true` and `extra.tool_result_metadata = {"is_error": true, "raw_tool_result": {...}}`, and the code is only available as text in `content` ("Exit code N"). Note also that the metadata sits on the **observation result's** `extra`, not on the step's `extra`. **For red-to-green method 1, read `tool_result_is_error` (red = true) and parse `^Exit code (\d+)` from `content` when you need the number.** A pass/fail signal exists. A structured integer does not. *Confirm on a Linux Harbor trial in Phase 0.*
- **`Skill` calls** appear as `function_name: "Skill"`, `arguments: {"skill": "<name>"}` (confirmed in local transcripts). The skill body that Claude Code then injects becomes a following `user` step whose text starts "Base directory for this skill…" (Harbor comment at L1499–1515). A skill can also be read with `Read` on its `SKILL.md`, which is not a `Skill` call. The activation gate should count both.
- **Cost and tokens.** Per-step `metrics` come from Anthropic `usage`. `final_metrics.total_cost_usd` is taken from the `total_cost_usd` in Claude Code's own stream-json `result` event (`claude-code.txt`). Harbor uses a LiteLLM estimate only as a fallback (L1001–1100, L1625–1630). For a local model behind a proxy, the cost is whatever Claude Code computes for that model name, so it may not be `None`. *Not verified.*

## 6. Custom model endpoint (local model tier)

- **The PRD flags do not exist in v0.24.0.** No source, doc, or example contains `--base-url`, `--api-key-name`, `--api-format`, or `--skip-model-parsing-and-provider-mapping`. No `agent-auth-resolution.mdx` page exists either. (Similar flag names appear only inside other adapters' own CLIs, for example `mcode`'s `--base-url`/`--api-format`.)
- **How it actually works for `claude-code`.** `MODEL_CONNECTION = ModelConnectionSpec(default_provider="anthropic", api_key_envs=("ANTHROPIC_API_KEY","ANTHROPIC_AUTH_TOKEN"), base_url_envs=("ANTHROPIC_BASE_URL",))` (`claude_code.py` L124–128). `resolve_model_connection` reads those env names from, in order, the agent's resolved env, the agent `env:`/`--ae` values, and the host `os.environ` (`src/harbor/agents/model_connection.py` L184–259; `base.py` L675–682). If `ANTHROPIC_BASE_URL` is found, `run()` exports it. It also sets `ANTHROPIC_MODEL` **and** `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` to the same model (`claude_code.py` L1782–1812, L1870–1880).
- **Model-name rule.** With a configured base URL, `model_name` is passed **verbatim**, including any `local/` prefix. Without one, the part before the last `/` is removed (L1745–1757). The proxy must accept the exact string, for example `local/qwen3-coder-30b-a3b-q5_k_m`.
- **A working shape for the local tier** (derived from the source, not run):

  ```yaml
  timeout_multiplier: 3.0            # job level; there is no per-agent field
  agents:
    - name: claude-code
      model_name: local/qwen3-coder-30b-a3b-q5_k_m
      concurrency_group: local-llm
      n_concurrent: 1
      env:
        ANTHROPIC_BASE_URL: http://host.docker.internal:4000
        ANTHROPIC_API_KEY: dummy
      kwargs:
        version: "<pinned claude-code version>"
  ```

  Remove `base_url`, `api_format`, and the per-agent `timeout_multiplier` (silently ignored). Remove `kwargs.model_info` (preflight error for `claude-code`). Model metadata for L6 has to go somewhere Harbor keeps, such as the job name or a sidecar file, because `AgentConfig` has no free-form field apart from `kwargs`, which is strict.
- **`ollama-job.yaml`** exists at `examples/configs/features/ollama-job.yaml`. It runs **`terminus-2`** with `model_name: ollama/qwen2.5-coder:7b` and `kwargs.model_info` (which is valid for terminus-2), with `n_concurrent_trials: 1` and job-level `timeout_multiplier: 1.5`. It is not an example of `claude-code` against a local endpoint.

## 7. `extra_hosts` via `--extra-docker-compose`, and the egress sidecar

- **Flag:** `--extra-docker-compose <file>`, repeatable (`src/harbor/cli/jobs.py` L930–938), or `environment.extra_docker_compose:` in job YAML (example: `examples/jobs/extra-docker-compose/config.yaml`). Each overlay is recorded in the lock with a digest (`ExtraDockerComposeLock`, `lock.py`). Any overlay switches the environment into compose mode (`docker.py` `_uses_compose`).
- **No automatic `host.docker.internal`.** Nothing in `src/` adds `host-gateway`. On Linux the overlay must add `services.main.extra_hosts: ["host.docker.internal:host-gateway"]`. With Rancher Desktop's dockerd inside WSL2, Phase 0 should check what `host-gateway` resolves to, and whether the model server on the Windows side (or the Ryzen box) is reachable from there.
- **L7 caveat confirmed.** The egress sidecar is enabled only if the startup, agent, or verifier network policy is not `public` (`docker.py` L297–307). When it is enabled, `_egress_controlled_service_names` routes `main` and every user compose service that has **no** `network_mode` or `networks` key through `network_mode: service:<sidecar>`. A service that declares either key is left alone, with no warning, which is the "allowlist stops without a message" failure the PRD describes (`docker.py` L375–388, L446–504).
- **Extra catch (Docker behaviour, not Harbor code; not verified by a run).** When the sidecar is active, `main` gets `network_mode: service:…`, and Docker rejects `extra_hosts` together with a container/service network mode ("conflicting options: custom host-to-IP mapping and the network mode"). `extra_hosts` on `main` therefore works only while every policy stays `public`, which is the task default (`src/harbor/models/task/config.py` L70). If the local tier ever needs an allowlist, put `extra_hosts` on the sidecar service instead, and add the host to `allowed_hosts`.

## Open points this research could not close

1. Whether a `hooks` key passed through `--settings` fires (Phase 0 marker trial).
2. The ATIF exit-code shape on a real Linux Harbor trial, compared with the Windows transcripts used here.
3. What `total_cost_usd` Claude Code reports for a non-Anthropic model name behind a proxy.
4. Whether Rancher Desktop (dockerd) plus WSL2 runs `docker compose` with `host-gateway` correctly.
