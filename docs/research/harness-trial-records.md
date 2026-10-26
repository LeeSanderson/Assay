# Which harnesses Harbor 0.24 runs, and how close each gets to a full trial record

Research for issue #45 (map #44). Question: which **harnesses** can Harbor 0.24 run, and for each one how close can it get to a full **trial record** (every tool call in order with verbatim arguments and results, tokens, cost, time, and the repository's history snapshotted per tool call or per turn)?

Sources: the pinned Harbor at `.venv/Lib/site-packages/harbor/` (Harbor 0.24, from `uv.lock`); `instruments/agent.py`, `instruments/trace.sh`, ADR 0001 and PRD "Adapter choice and trajectory fidelity"; opencode source at tag `v1.19.4` (latest release, 2026-10-22) in `github.com/anomalyco/opencode` and its docs at opencode.ai; pi source on `main` of `github.com/earendil-works/pi` (npm `@earendil-works/pi-coding-agent`, latest 1.4.0) and its docs at pi.dev; Codex source on `main` of `github.com/openai/codex` (latest release 0.164.0) and its docs (developers.openai.com, now redirecting to learn.chatgpt.com); the llama.cpp server README on `master`. Each claim names its source. **Unconfirmed** marks what was not checked in practice. Nothing here was run in a trial.

## Short answer

- Harbor 0.24 ships 47 agent names, about 40 of them coding harnesses (`models/agent/name.py` `AgentName`). Most of them write ATIF. The three that matter for Assay besides Claude Code (`opencode`, `pi`, `codex`) all write ATIF with verbatim tool arguments, and each harness has a native extension point that fires after every tool call and can run a shell command. So **each of the three can produce a full trial record with per-tool-call snapshots**, through a custom agent subclass in the same shape as `InstrumentedClaudeCode` (ADR 0001).
- What differs is how much of the record Harbor's ATIF already holds and what a recorder must add:
  - **pi** is the closest to Claude Code: `isError` per tool result, timestamps per event, and an extension API with `tool_result`/`tool_execution_end` events and `pi.exec()`.
  - **Codex** has Claude-Code-shaped hooks (`PostToolUse` with `hook_event_name`, `tool_name`, `tool_use_id` on stdin), so `trace.sh` may work almost unchanged. But Codex speaks only the OpenAI **Responses** API, and Harbor computes its cost from LiteLLM, not from Codex.
  - **opencode** loses the most in Harbor's conversion: a failed tool call has **no observation** in the ATIF, and the exit code and per-tool times are dropped. Its plugin hook `tool.execute.after` gets the exit code, but it **does not fire when a tool throws**.
- **One Harbor job can hold agents of different harnesses.** `JobConfig.agents` is a list, and the trials are `attempts × tasks × agents`. But `extra_instructions` are job-level, and an instruction file has no Harbor support for any harness. So the ADR 0004 shape (one job per condition) still fits.

## 1. The table

| | `claude-code` (today) | `opencode` | `pi` | `codex` |
|---|---|---|---|---|
| ATIF from Harbor | yes | yes (from `opencode run --format=json` stdout) | yes (from pi's session JSONL) | yes (from Codex rollout JSONL) |
| Verbatim tool arguments | yes | yes (`state.input`) | yes (`toolCall.arguments`) | yes (parsed JSON args, plus `extra.raw_arguments`; an edit is an `apply_patch` patch, not path + content) |
| Tool result for a failed call | yes, `extra.tool_result_is_error` | **missing**: Harbor reads only `state.output`, and an error state has `state.error` instead | yes, `extra.is_error` per result | yes (output text) |
| Exit code | in content of failed calls only | dropped by Harbor (it is in `metadata.exit` of the shell result) | not a field (in the content text, unconfirmed) | in the content text: `Process exited with code N` |
| Tokens per step | yes | yes, per step (`step_finish`) | yes, per message | yes, per API call (`token_count`) |
| Cost | Harbor/LiteLLM estimate | opencode's own `cost` (models.dev pricing) | pi's own `usage.cost.total` | Harbor's LiteLLM estimate; `None` for an unknown model |
| Time | per step | per step only (tool start/end times dropped) | per event | per event |
| Per-tool-call hook | `PostToolUse`, `PostToolUseFailure` (settings) | plugin `tool.execute.after` (success only) | extension `tool_result` / `tool_execution_end` (success and error) | `PostToolUse` hook (`config.toml` `[hooks]` or `hooks.json`) |
| Per-turn hook | `Stop` | `session.idle` event, step boundaries | `turn_end` | `Stop` |
| Skills via Harbor | yes | yes → `~/.config/opencode/skills` | yes → `~/.agents/skills` | yes → `~/.agents/skills` |
| MCP via Harbor | yes | yes (into `opencode.json`) | yes, but pins pi to `>=0.84.1,<0.86.0` | yes (into `config.toml`) |
| Native settings via Harbor | `kwargs.config` → `--settings` | `kwargs.opencode_config` → `opencode.json` | none (only `thinking`, `max_turns`, `model_api`) | `kwargs.config` → `$CODEX_HOME/config.toml` |
| Instruction file it reads | `CLAUDE.md` | `AGENTS.md` (falls back to `CLAUDE.md`) | `AGENTS.md` or `CLAUDE.md` | `AGENTS.md` |
| Anthropic `/v1/messages` | yes | yes (`anthropic/…` + `ANTHROPIC_BASE_URL`) | yes (`model_api: anthropic-messages`) | **no** |
| OpenAI Chat Completions | no | yes (custom provider in `opencode_config`) | yes (`model_api: openai-completions`) | **no** (`wire_api = "chat"` is removed) |
| OpenAI Responses | no | yes (`openai/…`, unconfirmed which API it uses) | yes (`openai-responses`) | yes, the only option |
| Local `llama-server` | yes, tested (`/v1/messages`) | yes, via either API (unconfirmed in practice) | yes, via either API (unconfirmed in practice) | only through `/v1/responses` (unconfirmed for the reference fork) |

## 2. Harbor 0.24: the agents and the job

- **The agent list.** `AgentName` has 47 values (including the non-harness `oracle` and `nop`), among them `claude-code`, `opencode`, `pi`, `codex`, `gemini-cli`, `qwen-coder`, `goose`, `cline-cli`, `cursor-cli`, `copilot-cli`, `kimi-cli`, `openhands`, `openhands-sdk`, `mini-swe-agent`, `swe-agent`, `terminus-2`, `aider`, `acp` (a generic Agent Client Protocol runner) and others (`models/agent/name.py`).
- **Capabilities.** Each agent declares `capabilities = AgentCapabilities(atif=…, skills=…, mcp_servers=…, native_config=…, …)` (`agents/capabilities.py`). ATIF is declared by `claude-code`, `opencode`, `pi`, `codex`, `gemini-cli`, `qwen-coder`, `goose`, `cline-cli`, `cursor-cli`, `copilot-cli`, `kimi-cli`, `hermes`, `junie`, `openhands`, `openhands-sdk`, `mini-swe-agent`, `swe-agent`, `terminus-2`, `vibe`, `acp` and others. No ATIF: `aider`, `code-puppy`, `deerflow`, `kimi-code`, `mcode`, `langgraph`, `fx` (the `capabilities =` lines in `agents/installed/*.py`).
- **Harnesses outside the three were not studied in depth.** `gemini-cli` (and its fork `qwen-coder`) declare ATIF, skills and MCP, and Gemini CLI has its own hook system, so it is the next candidate. Its endpoint is Google's API, not Anthropic or OpenAI. This was not checked further (**unconfirmed**). `mini-swe-agent` and `terminus-2` stay excluded for the PRD's reason (no verbatim file arguments).
- **One job, several harnesses.** `JobConfig.agents: list[AgentConfig]` (`models/job/config.py` line 428). Each `AgentConfig` has its own `name` or `import_path`, `model_name`, `kwargs`, `env`, `skills` and `mcp_servers` (`models/trial/config.py` lines 63–150). The trial list is `for _ in range(n_attempts) for task_config in task_configs for agent_config in config.agents` (`job_plan.py` lines 165–167). So a mixed job works. `extra_instruction_paths` and `extra_instructions` are on `JobConfig`, so they reach every agent in the job (`models/job/config.py` lines 438–451).
- **Instruction file.** No Harbor agent writes `AGENTS.md`, `CLAUDE.md` or `GEMINI.md` (grep of `agents/installed/*.py`: no matches). An instruction file is Assay's job, for example in the recorder subclass's `setup()`. It should go to the harness's **global** location rather than into `/app`, because a file in `/app` would enter the seed snapshot and the verifier's repository: Claude Code `~/.claude/CLAUDE.md`; opencode `~/.config/opencode/AGENTS.md` (opencode.ai/docs/rules); pi `<agent-dir>/AGENTS.md`, default `~/.pi/agent/` (pi.dev/docs/latest/configuration); Codex `$CODEX_HOME/AGENTS.md` (learn.chatgpt.com/docs/agent-configuration/agents-md). Note that Harbor moves the pi agent directory to `/tmp/harbor-pi-agent` when MCP or a custom endpoint is set (`pi.py` `_PI_CONFIG_DIR_ENV`), and sets `CODEX_HOME=/tmp/codex-home`, which it deletes after the run (`codex.py` `run()`).
- **Endpoints.** Harbor resolves the API key and base URL from the job's `env` per provider (`agents/model_connection.py`): `anthropic` reads `ANTHROPIC_BASE_URL`, `openai` reads `OPENAI_BASE_URL`/`OPENAI_API_BASE`. `opencode` and `pi` pass these through unchanged (`passthrough=True`). `codex` fixes the provider to `openai` (`ModelConnectionSpec(default_provider="openai")`).

## 3. opencode

**ATIF fidelity** (`agents/installed/opencode.py`):

- Harbor runs `opencode --model=<provider/model> run --format=json --thinking --dangerously-skip-permissions` and parses the stdout JSON lines (`run()`, `_convert_events_to_trajectory`). One ATIF step per `step_start`…`step_finish` pair, with that step's text, reasoning, tool calls and results.
- Tool arguments are `part.state.input`, verbatim (lines 349–365).
- The observation is added only `if tool_output is not None`, from `state.output` (lines 367–373). In opencode, a failed tool call's state is `{status: "error", input, error, metadata, time}`: it has no `output` (`packages/opencode/src/session/processor.ts` `failToolCall`, v1.19.4). So **a failed call has no observation and no error flag** in the ATIF. Its call is still recorded.
- The shell tool's result has `metadata.exit` (the exit code) (`packages/opencode/src/tool/shell.ts` lines 585–592, v1.19.4). Harbor does not copy `metadata` into the ATIF. Each tool state also has `time.start`/`time.end`; Harbor uses only the step's `timestamp`.
- Tokens and cost come from `step_finish` (`tokens.input/output/reasoning/cache`, `cost`) per step (lines 375–407). The cost is opencode's own; for a model unknown to opencode's catalog it is presumably 0, which Harbor writes as `None` (**unconfirmed**).

**Hook for a per-tool-call snapshot.** opencode plugins (opencode.ai/docs/plugins):

- Loaded automatically from `~/.config/opencode/plugins/` (global) and `.opencode/plugins/` (project), or from npm via the `plugin` key in `opencode.json`. A plugin gets `$`, Bun's shell API, so it can run `trace.sh`.
- Signature (`packages/plugin/src/index.ts`, v1.19.4): `"tool.execute.after"?: (input: { tool, sessionID, callID, args }, output: { title, output, metadata }) => Promise<void>`.
- It is awaited: `yield* plugin.trigger("tool.execute.after", …)` runs before the tool result returns (`packages/opencode/src/session/tools.ts` lines 121–129, v1.19.4).
- **It fires only on success.** The trigger comes after `yield* item.execute(args, ctx)`; if `execute` throws, the trigger is skipped (same file). A shell command with a non-zero exit does not throw: it returns with `metadata.exit` set. The calls that throw are tool errors such as a bad edit or a missing file. Those rarely change the repository, and the next successful call's snapshot catches any change, but the record would state "per successful tool call".
- opencode has its own `snapshot` feature (`packages/core/src/config/plugin/snapshot.ts`, and Harbor sets `OPENCODE_FAKE_VCS=git`). Whether it could serve as a per-step repository history was not checked (**unconfirmed**).

**Configuration.** `kwargs.opencode_config` is deep-merged into `~/.config/opencode/opencode.json` (`_build_register_config_command`), so settings, the `instructions` key and `plugin` entries can go there. Skills are copied to `~/.config/opencode/skills/`. MCP servers are written as `mcp.<name>` with `type: local|remote`. `disable_web_search` denies `websearch` and `webfetch`.

**Endpoints.** The model name must be `provider/model`. For `anthropic`, `google` or `openai`, Harbor writes the configured base URL to `provider.<p>.options.baseURL` (lines 545–553), so `anthropic/<model>` with `ANTHROPIC_BASE_URL` reaches a `/v1/messages` server. For a Chat Completions server, opencode's docs use a custom provider with `"npm": "@ai-sdk/openai-compatible"` and `options.baseURL` (opencode.ai/docs/providers); that goes in `opencode_config`. Not tried against `llama-server` (**unconfirmed**).

## 4. pi

**ATIF fidelity** (`agents/installed/pi.py`):

- Harbor runs `pi --print --mode json --session-dir <logs>/pi/sessions --provider <p> --model <m> [--extension …]` and converts the session JSONL, not stdout (`run()`, `_load_trajectory`). It follows the active branch of pi's session tree (`_active_session_events`).
- One ATIF step per assistant message, with its `toolCall` blocks as tool calls (`id`, `name`, `arguments` verbatim) (lines 872–888). Each `toolResult` message becomes an observation result with `extra.tool_name` and `extra.is_error` (lines 943–954). Each event has its own `timestamp`.
- Tokens and cost are from each message's `usage` (`input`, `output`, `cacheRead`, `cacheWrite`, `cost.total`) (`_metrics_from_usage`). pi prices from its model catalog. For a custom endpoint, Harbor's generated `models.json` has no `cost` block (`_build_custom_models_json`), and pi's docs say a model without a price reports tokens at no cost (pi.dev/docs/latest/models), so a local model costs `None`.

**Hook for a per-tool-call snapshot.** pi extensions (pi.dev/docs/latest/extensions; `packages/coding-agent/src/core/extensions/types.ts`):

- Events per tool call, in order: `tool_execution_start`, `tool_call`, `tool_execution_update`, `tool_result`, `tool_execution_end`. `ToolResultEvent` has `toolCallId`, `input`, `content`, `isError`. `ToolExecutionEndEvent` has `toolCallId`, `toolName`, `result`, `isError`, `durationMs`. Per turn: `turn_end` with `toolResults`.
- The extension API has `exec(command, args, options): Promise<ExecResult>` (`types.ts` line 1767), so an extension can run `trace.sh`.
- `tool_result` handlers can change the result, so pi must await them. Whether `tool_execution_end` handlers are awaited is not stated (**unconfirmed**).
- Caveat: "Calls from one assistant message can run in parallel" (extensions doc). A snapshot per call then can see the combined effect of parallel calls. Claude Code can also run tool calls in parallel; how `trace.sh` deals with that is out of scope here.
- Loading: `--extension <file>`, or `<agent-dir>/extensions/` (default `~/.pi/agent/extensions/`, moved by `PI_CODING_AGENT_DIR`) (pi.dev/docs/latest/configuration). Harbor already passes `--extension` for its own MCP adapter and `max_turns` extension (`pi.py` lines 412–422). Harbor's `max_turns` extension is itself a working example of `pi.on("turn_end", …)`.

**Configuration.** Skills go to `~/.agents/skills`, which pi reads (pi.dev/docs/latest/skills). MCP needs Harbor's pinned `pi-mcp-adapter@2.34.0` and pi `>=0.84.1,<0.86.0` (`pi.py` lines 53–55, 143–157); the current pi is 1.4.0 (npm). There is no native-settings passthrough: `PiOptions` has only `thinking`, `model_api` and `max_turns`. Settings would need the recorder subclass.

**Endpoints.** With a configured base URL, Harbor requires `kwargs.model_api` and writes a `harbor-endpoint` provider to `models.json` (`_build_custom_models_json`). pi's `api` values include `anthropic-messages`, `openai-completions`, `openai-responses` and `google-generative-ai` (pi.dev/docs/latest/models-configuration). So pi can reach `llama-server` through `/v1/messages` or `/v1/chat/completions` (**unconfirmed** in practice).

## 5. Codex

**ATIF fidelity** (`agents/installed/codex.py`):

- Harbor runs `codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --model <m> --json --enable unified_exec` and converts the rollout JSONL from `$CODEX_HOME/sessions` (`run()`, `_convert_events_to_trajectory`).
- `function_call` and `custom_tool_call` items become tool calls. The arguments are parsed from JSON; a non-JSON input (such as an `apply_patch` patch) becomes `{"input": <raw>}`, and the raw text is kept in `extra.raw_arguments` (lines 1318–1351, 940–943). A file edit is therefore a patch, not a path plus full content. Analysis that expects `Write`/`Edit` arguments must parse patches.
- Tool outputs become observations (lines 1357–1385). With `unified_exec`, the output text has `Process exited with code N` when the process has exited (`codex-rs/core/src/tools/context.rs` line 579). A process still running returns `Process running with session ID …` instead, and its exit arrives through a later `write_stdin` call.
- Tokens come from `token_count` events per API call. Codex reports no cost: Harbor prices each call with LiteLLM and returns `None` for a model not in LiteLLM's table (`_compute_cost_from_pricing`). The zero-price registration in `InstrumentedClaudeCode.__init__` would apply here too.

**Hook for a per-tool-call snapshot.** Codex hooks (developers.openai.com/codex/hooks → learn.chatgpt.com/docs/hooks):

- Events include `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `SessionStart`, `SessionEnd`. `PostToolUse` covers shell (`Bash`), unified exec (`exec_command`), `apply_patch` (matched as `apply_patch`, `Edit` or `Write`), MCP tools and other local function tools. It does not cover hosted tools such as web search.
- The stdin JSON has `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `turn_id`, and for tool events `tool_name`, `tool_use_id`, `tool_input`, `tool_response`. These are the fields `trace.sh` reads today (`hook_event_name`, `tool_name`, `tool_use_id`).
- There is no `PostToolUseFailure` event in the list. Whether `PostToolUse` fires for a failed call is not stated (**unconfirmed**).
- Configured as `[hooks]` in `config.toml` or as `hooks.json` in a config layer. Non-managed hooks must be trusted; `--dangerously-bypass-hook-trust` skips this for one run. Harbor exposes it as `kwargs.dangerously_bypass_hook_trust` (`CodexOptions`). Hooks are on by default.
- So a recorder can merge a `[hooks]` table into `kwargs.config` (Harbor uploads it as `$CODEX_HOME/config.toml`, `_build_effective_config`), the same pattern as `merge_instrument_hooks`.

**Configuration.** `kwargs.config` (TOML path or inline JSON) is the base `config.toml` (`native_config=True`). Skills go to `$HOME/.agents/skills`, which Codex scans as USER scope (learn.chatgpt.com/docs/build-skills). MCP servers go into `mcp_servers` in `config.toml`. `disable_web_search` sets `web_search=disabled`.

**Endpoints.** Codex's `WireApi` enum has only `Responses`; `"chat"` fails with `CHAT_WIRE_API_REMOVED_ERROR` (`codex-rs/model-provider-info/src/lib.rs` lines 111–136). Harbor writes `OPENAI_BASE_URL` into `openai_base_url` in `config.toml` (`codex.py` lines 1726–1738) and passes only the last segment of the model name. So Codex cannot use an Anthropic endpoint. It can use `llama-server` only through its `/v1/responses` endpoint, which upstream llama.cpp has (`tools/server/README.md`, "POST /v1/responses"). Not checked: whether the reference fork commit `c49ebdb` has it, and whether llama-server's Responses implementation accepts Codex's custom (freeform) `apply_patch` tool (**unconfirmed**).

## 6. Bottom line for the trial record

- All three can give every tool call in order with verbatim arguments, tokens, time and a repository snapshot per tool call, through a recorder subclass that installs a per-harness hook (opencode plugin, pi extension, Codex `[hooks]`) that calls the shared `trace.sh`.
- Each recorder must fill gaps in Harbor's ATIF, or the record must say what it lacks:
  - opencode: failed calls have no result and no error flag; exit codes and tool times are dropped; the hook misses calls that throw. A recorder can recover these from the hook (`metadata.exit`) and from opencode's own session export, or from a patched conversion.
  - pi: nearly complete; an exit code is only in the result text (**unconfirmed**).
  - Codex: edits are patches; the exit code is in the result text; cost depends on LiteLLM.
- Endpoint reach limits the harness factor for the local tier: Claude Code, opencode and pi can use `/v1/messages`; Codex needs `/v1/responses`.
