# Inference server and Anthropic route for the local tier on a Ryzen AI Max+ 395

Research for [issue #3](https://github.com/LeeSanderson/Assay/issues/3) (map: [issue #1](https://github.com/LeeSanderson/Assay/issues/1)). Researched 2026-10-18. It covers PRD section 5, "Model tiers, and the local tier", requirements L1 to L8, and Risks 9 and 10.

**Scope.** The question is which inference server and which Anthropic Messages route fit a Ryzen AI Max+ 395 (Strix Halo, gfx1151, Radeon 8060S, 128 GB unified memory). The server answers Harbor's `claude-code` adapter with `--api-format anthropic`. It also asks what throughput to expect, so that Risk 10 (local tier wall clock) can be sized. The final model choice is out of scope; it belongs to ticket #4. This document lists options and trade-offs only.

**Trust labels used below.**
- **[P]** Primary: the project's own docs, source code, release notes or issue tracker, or AMD/Anthropic docs.
- **[R]** Reproducible third party: published raw data with the hardware, OS, kernel and build recorded.
- **[S]** Secondary: a blog or forum post. The numbers are plausible but the method is not fully published.

---

## 1. Answer in brief

| | Linux (recommended) | Windows |
|---|---|---|
| Inference server | **llama.cpp `llama-server`**, ROCm build (`ubuntu-rocm-10.0` release asset or the kyuz0 `rocm-*` toolbox). Use Vulkan RADV if a model decodes faster on it. | **llama.cpp `llama-server`**, `win-vulkan-x64` or `win-rocm-10.0-x64` release asset. LM Studio and Ollama are the GUI alternatives. |
| Anthropic route | **Native** `POST /v1/messages` in `llama-server`. No proxy. | The same: native `/v1/messages` in llama-server, LM Studio (≥ 0.4.1) or Ollama. |
| Proxy (LiteLLM) | Not needed. Keep it only as a fallback for a server that has no `/v1/messages` (for example an older vLLM). | Not needed. |
| Harbor host | Native Docker. L7 applies as written. | Harbor runs in WSL2 Docker, and the server runs on the Windows host. The host route still has to be proven. |

**The main breakage (verified in source).** Claude Code now sends a `role: "system"` message in the middle of `messages[]`. llama.cpp passes it through to the Jinja chat template unchanged. Qwen-family templates then raise `System message must be at the beginning`, so **every request fails with HTTP 400**. The fix is a patched chat template per model (`--chat-template-file`). See §3.

**Throughput.** A 30B-class A3B MoE gives about 1,100 tok/s prompt processing at short context and about 500 to 800 tok/s at 32k depth. Generation runs at about 45 to 100 tok/s, depending on quant and backend. **Estimated local tier wall clock for 180 trials: about 15 to 30 hours** if the KV prefix cache holds, and **120 to 200 hours** if every turn has to reprocess the whole context. See §4.

---

## 2. Which inference servers run well on this chip (Linux and Windows)

### 2.1 Platform: ROCm on gfx1151

- **Linux.** AMD's Strix Halo optimisation page lists gfx1151 kernel requirements for ROCm 10.0.0/10.1.0, 7.14.x and 7.2.1 to 7.2.4, and marks those versions stable on the required kernels. ROCm 7.1.x and 6.4.x are unsupported on the newer kernels. The minimum kernels are Ubuntu 24.04 HWE `6.17.0-19.19~24.04.2`, Ubuntu 24.04 OEM `6.14.0-1018`, or `6.18.4` on other distributions. Fedora 43, Ubuntu 26.04 and Arch 2026.02.01 ship the fixes natively. The page recommends a small BIOS VRAM carve-out (for example 0.5 GB) and a larger GTT/TTM limit, set with `amd-ttm --set <GB>` from `amd-debug-tools`. [P] <https://rocmdocs.amd.com/en/develop/how-to/system-optimization/strixhalo.html>
- **Windows.** The ROCm Core SDK 10.0.0 release notes list the Ryzen AI Max+ 395 (gfx1151) with Windows 11 25H2 support for HIP. [P] <https://rocm.docs.amd.com/en/develop/about/release-notes.html>. The HIP SDK for Windows system requirements also list gfx1151 as supported for the runtime and the SDK. [P] <https://rocm.docs.amd.com/projects/install-on-windows/en/latest/reference/system-requirements.html>
- The `HSA_OVERRIDE_GFX_VERSION` workaround in older community guides should no longer be needed on current ROCm. [S]

### 2.2 Servers

| Server (latest at 2026-10-18) | Linux on gfx1151 | Windows on gfx1151 | Native Anthropic `/v1/messages` | Notes |
|---|---|---|---|---|
| **llama.cpp** `llama-server` (b11719; release v0.7.0 on 2026-10-15) | Yes. Release assets `ubuntu-rocm-10.0-x64` and `ubuntu-vulkan-x64` [P]. The kyuz0 toolboxes (Fedora) track master with stable `vulkan-radv` and `rocm-10.0` images [P/R]. | Yes. Release assets `win-vulkan-x64` and `win-rocm-10.0-x64` [P]. | **Yes**, since PR #17570 (announced 2026-01-19). Endpoints are `/v1/messages` and `/v1/messages/count_tokens`, with streaming, tools, thinking and images. **Tool use needs `--jinja`**, which is now the default. [P] | Default port **changed to 9931** in v0.7.0 (#30159). Docker images keep 8080. PRD's `:4000` must be set explicitly. kyuz0 advises `-fa 1` and `--load-mode none` on Strix Halo to avoid crashes and slowdowns. |
| **Ollama** (v0.40.6) | Yes. ROCm list names "Ryzen AI Max+ 395" (gfx1151). Vulkan is enabled by default (`OLLAMA_VULKAN=0` disables it). [P] | Vulkan only. The Windows ROCm table does not list gfx1151. [P] | **Yes.** Streaming, tools, thinking (budget not enforced), base64 images. **Not supported:** `tool_choice`, `count_tokens`, prompt caching (`cache_control`), PDF blocks, streamed `error` events. [P] | Wraps llama.cpp (ggml). Its docs recommend ≥ 64k context for Claude Code [P]. Less control over flags (`--chat-template-file`, cache sizes) than llama-server. |
| **LM Studio** | Linux app plus headless `llmster`. | Yes, the main platform. | **Yes**, `POST /v1/messages` since 0.4.1. Its docs set `CLAUDE_CODE_ATTRIBUTION_HEADER=0` and require > ~25k context. [P] | Its docs do not say which AMD runtime (Vulkan/ROCm) it uses on gfx1151. Not verified. A Claude Code grammar crash with 30+ tools was reported on 0.4.20 (bug tracker #2236). [P, issue] |
| **vLLM** (v0.32.0) | Only through community builds. kyuz0's `amd-strix-halo-vllm-toolboxes` tracks ROCm 10.0 and stable vLLM with gfx1x/APU patches (AITER off, no `ROCM_AITER_FA`). **No published benchmarks for the current image.** [P/R] | No. vLLM is Linux-only. | Yes, in current releases. Claude Code ≥ 2.1.154 broke it (400 "Input should be 'user' or 'assistant'") until PR #44283, closed 2026-06-02 (issue #44000). [P] | Built for high-concurrency batching. L3 fixes `n_concurrent = 1`, so vLLM's main strength is unused. Highest setup risk. |
| **Lemonade** (AMD; v2026.42.1) | Yes, ROCm/Vulkan llama.cpp backends. | Yes. | Claims Anthropic compatibility, **but issue #2662 is open**. It silently drops the mid-array `system` message, `thinking: adaptive` and `metadata`, giving empty `end_turn` replies and multi-minute stalls with Claude Code. It was reproduced on 2026.42.1 on 2026-10-17. [P, issue] | **Avoid for the local tier until #2662 is fixed.** |
| **LiteLLM proxy** (v1.106.0) | Runs anywhere. | Runs anywhere. | Exposes `/v1/messages` for "all LiteLLM supported providers" and translates to OpenAI-format backends. Streaming, tools and thinking fields are accepted. [P] | It adds a translation layer, while Claude Code's gateway guide says to forward bodies and `anthropic-*` headers unchanged. Every server above already speaks Anthropic natively, so LiteLLM only adds failure modes. Keep it only as the Risk 9 fallback for an OpenAI-only server. |

**Recommendation.** Use **`llama-server` with its native `/v1/messages`** on both operating systems. It has the most Strix Halo benchmark data. It exposes the controls the local tier needs (`--chat-template-file`, `--parallel`, `--cache-ram`, ctx size), and L6 can record it exactly (release tag plus backend asset). It also has the shortest request path, because no proxy sits between Claude Code and the template.

**Prefer Linux for the box.** Every reproducible benchmark below is from Linux (Fedora). Harbor's Docker stack is Linux-native, and L7 is written for Linux. On Windows, Harbor would run inside WSL2 and reach a server on the Windows host. That is workable, but not verified here.

### 2.3 Backend choice: ROCm vs Vulkan

These figures come from kyuz0's results file: `llama-bench`, Fedora 43, kernel 6.19.12, llama.cpp b9187/b9193, generated 2026-05-18, flash attention on, logs per run. [R] <https://github.com/kyuz0/amd-strix-halo-toolboxes/blob/main/docs/results.json>

- **Prompt processing at long context:** ROCm usually wins, often by a large margin. For example, gpt-oss-120b pp2048 at 32k depth is 589 to 653 tok/s on ROCm and 307 on RADV. Prefill at depth dominates agentic coding, because every turn re-sends a large context.
- **Generation:** Vulkan RADV often wins at short depth. For example, Qwen3.6-35B-A3B Q4 tg128 is 60.4 tok/s on RADV and 51.5 on ROCm 7.2.3.
- **Exceptions:** BF16 weights decode about 2.5× slower on Vulkan. GLM-4.7-Flash prefill is faster on Vulkan.
- **AMDVLK** is never the best choice. Don't use it.

The choice is per model, so it belongs in the L6 record.

---

## 3. Anthropic Messages route and known Claude Code breakages

### 3.1 What Claude Code requires of an `ANTHROPIC_BASE_URL` endpoint [P]

Source: Claude Code gateway compatibility guide, <https://code.claude.com/docs/en/llm-gateway-protocol>

- **Endpoints.** It calls `/v1/messages`, posted as `/v1/messages?beta=true`. `/v1/messages/count_tokens` is optional; without it, Claude Code estimates usage from characters. It also sends a `HEAD /api/hello` warm-up probe that the server may reject.
- **Streaming.**
  - The server must stream event by event and must not buffer.
  - It must send the full event sequence through `message_delta` and `message_stop`.
  - Claude Code aborts after its streaming idle timeout. A changelog aggregator reports this was raised to 300 s for custom base URLs [S].
  - **Long prefill can trip this timeout** if the server sends no bytes while it processes the prompt.
- **Unrecognised model IDs** (such as a local alias) are treated as current Claude models. Claude Code then sends `thinking: {"type":"adaptive"}`, `output_config.effort` and context-management fields. It also assumes a 200K context window unless told otherwise.
- **Background model.** Background tasks use the main model unless `ANTHROPIC_DEFAULT_HAIKU_MODEL` pins another. **With one local server, background calls (titles, summaries, classifiers) share the single slot with the trial.**
- **Attribution block.** Claude Code adds an attribution block to the system prompt. Since v2.1.181 it is stable for the whole conversation, so prefix caching works. `CLAUDE_CODE_ATTRIBUTION_HEADER=0` removes it. llama.cpp also normalises the per-request `cch=` field in the billing header itself (`normalize_anthropic_billing_header` in `tools/server/server-chat.cpp`). [P, source]
- **`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`** removes `context_management`, the beta tool fields (`strict`, `defer_loading`), structured-output format and MCP tool search. It does **not** remove adaptive thinking, effort or the mid-conversation system message.
- **Support status.** Anthropic "doesn't support routing Claude Code to non-Claude models through any gateway" (<https://code.claude.com/docs/en/llm-gateway>). The local tier runs on an unsupported path, and any Claude Code release can break it.

### 3.2 Known breakages

| # | Breakage | Affects | Status (2026-10-18) | Mitigation |
|---|---|---|---|---|
| B1 | **Mid-conversation `role:"system"` message.** Claude Code puts harness context (agent list, skills list) in a trailing system message, even on the first request. Qwen-family Jinja templates raise `System message must be at the beginning`, so every request returns 400. | llama.cpp (and anything that renders the model's Jinja template), Qwen3/3.5/3.6/Coder templates. Reported on Claude Code 2.1.208 and reproduced on 2.1.235. | claude-code #77698 was **closed "not planned"** (stale bot) on 2026-09-21. No Claude Code fix. [P] <https://github.com/anthropics/claude-code/issues/77698>. llama.cpp's converter still passes non-leading system messages straight to the template (verified in `server-chat.cpp` on master). [P] | **Patch the model's chat template** to render a non-leading system turn, and load it with `--chat-template-file`. This is the only workaround verified end to end, and it is needed once per model. `--chat-template chatml` and `--no-jinja` break tool-call parsing. A shim that rewrites the 400 into Anthropic's `Unexpected role "system"` wording would trigger Claude Code's retry-without-system logic, but this is unverified. See also llama.cpp #27107 (Qwen3.8 27B, Windows). [P] |
| B2 | **Tool-argument enum quoting.** `anyOf` string enums arrived with literal quotes (Claude Code `TaskUpdate`), and schema validation failed. | llama.cpp b8733 to the fix | Fixed by PR #22827 (2026-05-08). [P] <https://github.com/ggml-org/llama.cpp/issues/22240> | Use any current build. |
| B3 | **Thinking blocks dropped** when converting Anthropic to the internal OpenAI format. | llama.cpp | Issue #20090. The converter now maps `thinking` blocks to `reasoning_content` (verified in source), so this is probably fixed but unconfirmed. [P] | Check in the Phase 0 trial. |
| B4 | **`thinking.type=disabled` and `output_config.effort` ignored** by llama.cpp's Anthropic route. | llama.cpp | PR #30608 is **open**. [P] | Low impact, but the model may think when Claude Code asked it not to. This costs tokens and wall clock. Control thinking in the model's template or server flags. |
| B5 | **Tool results before user text** in the Anthropic conversion. | llama.cpp | PR #29482 is **open**. [P] | Watch for it. Effect on trajectories unknown. |
| B6 | **vLLM rejects the `system` role** (400). | vLLM with Claude Code ≥ 2.1.154 | Fixed by PR #44283 (2026-06-02). [P] <https://github.com/vllm-project/vllm/issues/44000> | Use a vLLM release after that fix. |
| B7 | **Lemonade drops the system message, adaptive thinking and metadata**, giving empty replies and stalls. | Lemonade ≤ 2026.42.1 | **Open.** [P] <https://github.com/lemonade-sdk/lemonade/issues/2662> | Don't use Lemonade. |
| B8 | **Grammar parse failure with 30+ tools.** | LM Studio 0.4.20 | Reported. [P] lmstudio-bug-tracker #2236 | Check if LM Studio is used. |
| B9 | **Ollama does not support `cache_control`, `count_tokens` or `tool_choice`.** | Ollama | By design, per its docs. [P] | Harmless: Claude Code falls back. Ollama passes a mid-array system message through as `role: system` (verified in `anthropic/anthropic.go`); whether its Go template renders it was not verified. |
| B10 | **Login prompt** when only `ANTHROPIC_BASE_URL` is set. | All | Community reports in llama.cpp #27107 and on the HF blog. [S] | Set `ANTHROPIC_AUTH_TOKEN` (any value) and `ANTHROPIC_API_KEY=""`, as the Ollama docs do [P]. Harbor's `--api-key-name` should cover this. |

**What this means for L2 and Risk 9.**
- The Anthropic route works today, but only with a patched chat template for Qwen-family models.
- It can break on any Claude Code release, because Anthropic does not support this path. **Pin the Claude Code version Harbor installs** for the whole matrix, so that all three model tiers use the same agent. Record it with the L6 fields.
- The Phase 0 local trial should confirm two things: that the trajectory holds verbatim tool arguments, and that no 400s or retries hide in the log.

---

## 4. Throughput and Risk 10

### 4.1 Measured throughput on Ryzen AI Max+ 395, 128 GB (llama.cpp)

These are kyuz0 `llama-bench` figures [R]: Fedora 43, kernel 6.19.12, llama.cpp b9187/b9193, captured 16 May 2026. "pp" is prompt processing and "tg" is generation, both in tok/s. "d32k" means at 32,768 tokens of existing context.

| Model (quant, size) | Backend | pp512 | pp2048 @ d32k | pp2048 @ d64k | tg128 | tg32 @ d32k | tg32 @ d64k |
|---|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B UD-Q4_K_XL (21 GiB) | ROCm 7.2.3 | 1120 | 747 | 493 | 51.5 | 43.8 | 38.4 |
| | Vulkan RADV | 1114 | 716 | 525 | 60.4 | 49.2 | 43.2 |
| Qwen3.6-35B-A3B UD-Q8_K_XL (36 GiB) | ROCm 7.2.3 | 1094 | 729 | 486 | 46.2 | 40.0 | 35.5 |
| | Vulkan RADV | 1045 | 683 | 505 | 46.3 | 40.1 | 35.8 |
| gpt-oss-120b MXFP4 (59 GiB) | ROCm 7.2.3 | 626 | 589 | 371 | 51.8 | 36.3 | 26.1 |
| | Vulkan RADV | 720 | 308 | 146 | 56.6 | 43.0 | 35.0 |
| gpt-oss-20b MXFP4 (11 GiB) | ROCm 7.2.3 | 1786 | 1003 | 602 | 73.1 | 52.2 | 40.7 |
| Qwen3.5-122B-A10B UD-Q5_K_XL (86 GiB) | ROCm 7.2.3 | 337 | 276 | 192 | 20.1 | 17.7 | 15.7 |
| Nemotron-3-Super-120B-A12B UD-Q4_K_XL (78 GiB) | ROCm 7.2.3 | 276 | 382 | 348 | 14.9 | 14.4 | 14.0 |
| GLM-4.7-Flash UD-Q8_K_XL (33 GiB) | Vulkan RADV | 1092 | 137 | 74 | 41.2 | 22.6 | 15.7 |
| Qwen3.6-27B (dense) UD-Q8_K_XL (33 GiB) | ROCm 7.2.3 | 367 | 198 | 106 | 6.5 | 6.1 | 5.8 |
| MiniMax-M2.7 UD-Q3_K_S (87 GiB) | ROCm 7.2.3 | 243 | 143 | — | 23.1 | 6.2 | — |

**Qwen3-Coder-30B-A3B** (the PRD's example) is not in kyuz0's current set. Other sources:

| Source | Quant / build | pp512 | tg128 | Trust |
|---|---|---|---|---|
| Soothill, 2026-08-03 | Q4_K_S, ROCm b10085 | 1345 ± 30 (50 runs) | 73.7 ± 0.5 | [S]: builds differ between backends, no depth test, no raw data |
| Soothill, 2026-08-03 | Q4_K_S, Vulkan b10216 | 1115 (5 runs) | 97.7 | [S] |
| hogeheer499 strix-halo-guide | UD-Q4_K_XL, Vulkan b11146 | 1438 | 96.3 | [S]: the author notes the host was not idle |

The PRD's **Q5_K_M has no direct benchmark**. MoE decode on this chip is bandwidth-bound, so expect Q5_K_M to fall between the Q4 figures (about 75 to 98 tok/s tg) and the Q8 figures. That is an inference, not a measurement.

**Single-shot coding quality and latency** (Soothill custom 10-task suite, one response, Lemonade/llama.cpp, 2026-08-14) [S]: gpt-oss-120b 9/10, 21 s/task; Qwen3.6-35B-A3B Q6 6/10, 7 s/task; Qwen3-Coder-30B-A3B Q4 5/10, 4 s/task; Qwen3-Coder-Next Q5_K_M 5/10, 10 s/task. This is not an agentic benchmark. It only hints that a newer or larger model may solve more task packs.

### 4.2 Wall-clock model for one local trial

A Claude Code trial is a loop of turns. Each turn re-sends the whole context, and the server only has to prefill the **new** tokens when its prefix cache holds.

```
T_trial ≈ P0/pp(0) + N × ( Δin/pp(d) + out/tg(d) + t_tool )
```

**Assumptions** (Phase 0 replaces each one with a measured value):
- **P0**, the initial system prompt plus tools: about 17 to 25k tokens. llama.cpp discussion #19467 reports about 16 to 17k; LM Studio asks for more than 25k of context.
- **N**, the number of turns: 30 to 60.
- **Δin**, the new input per turn (tool results): about 1.5k tokens.
- **out**, the output per turn: about 300 tokens without thinking, about 800 with thinking.
- **d**, the typical context depth: about 32k.
- **t_tool**, tool execution time: about 3 s.

| Model | Cache holds, no thinking | Cache holds, thinking on | Cache misses every turn (re-prefill ~40k at pp@d32k) |
|---|---|---|---|
| Qwen3-Coder-30B-A3B Q4/Q5 (tg ~75, pp@d32k ~750, assumed like Qwen3.6-A3B) | ~6 min | ~10 min | ~40 to 60 min |
| Qwen3.6-35B-A3B Q8 (tg 40, pp 730) | ~9 min | ~17 min | ~45 to 65 min |
| gpt-oss-120b (tg 36 to 43, pp 590) | ~9 min | ~17 min | ~50 to 75 min |
| Qwen3.5-122B-A10B Q5 (tg 18, pp 276) | ~17 min | ~35 min | ~110+ min |

**Local tier, 180 trials (L3: `n_concurrent = 1`, so the trials run one after another):**

| Scenario | ~A3B model | gpt-oss-120b | ~A10B 122B model |
|---|---|---|---|
| Cache holds, no thinking | **18 to 27 h** | ~27 h | ~50 h |
| Cache holds, thinking on | 30 to 50 h | ~50 h | ~105 h |
| Cache misses | 120 to 195 h | 155 to 225 h | 330+ h |

These are planning ranges, not measurements. They do not include trials that end at the raised timeout (L4).

### 4.3 What this means for Risk 10

1. **A 30B-class A3B MoE with a working prefix cache keeps the local tier to about 1 to 2 days of wall clock.** That is acceptable, so the Risk 10 fallback (cut a language, or cut repetitions) is probably not needed for that model class. A 120B-class model roughly doubles the time. A dense 27B (6 tok/s) or MiniMax-class model at Q3 is not practical.
2. **Prefix-cache reuse is the main variable, not the raw tok/s.** A cache miss costs 5 to 7× more time. Claude Code's background requests (titles, summaries, classifiers) go to the same single model unless pinned elsewhere. With one slot they can evict the trial's cache. Mitigations, to verify in Phase 0:
   - Use `--parallel 2`, or keep `--cache-ram` on (default 8192 MiB; raise it, because 128 GB leaves room). It saves idle slots to RAM (`--cache-idle-slots`, default on).
   - Size `-c` per slot for the longest trial, and declare it to Claude Code with `/autocompact` or the model-config window, so that Claude Code does not assume 200K.
   - Keep the `system` array stable. Don't strip or move the attribution block.
3. **Thinking roughly doubles the time.** Whether the local tier runs with thinking on is a cell definition decision for #4.
4. **Long prefill vs the streaming idle timeout.** A cold 40k-token prefill at about 500 tok/s takes about 80 s, which is safe against 300 s. A 120B model at 64k depth (about 190 tok/s, about 340 s) could trip the timeout. Phase 0 should log the longest time-to-first-byte.
5. **Phase 0 measurement plan for Risk 10.** Time one local trial with the server's `/metrics` or `timings` enabled. Record N, P0, Δin, out and the cache hit rate. Then multiply by 180 and compare with the ranges above.

---

## 5. Options for ticket #4 (model choice), with no recommendation

| Option | Fits 128 GB? | Speed class | Notes |
|---|---|---|---|
| Qwen3-Coder-30B-A3B Q5_K_M (PRD example; July 2025) | Yes (~22 GB) | Fastest | Purpose-built for agentic coding, but the oldest option. Needs the B1 template patch. |
| Qwen3.6-35B-A3B Q4/Q8 | Yes (21 to 36 GB) | Fast | Newer Qwen generation with the best reproducible data on this chip. Needs the B1 patch. |
| Qwen3-Coder-Next 80B (A3B-class) Q5_K_M | Yes | Medium (tg ~44) [S] | Coding-tuned. Needs the B1 patch. |
| gpt-oss-120b MXFP4 | Yes (59 GB) | Medium | Highest single-shot score in Soothill's suite [S]. Uses a non-Qwen (harmony) template, so B1 may not apply. Not verified. |
| Qwen3.5-122B-A10B Q5 / Nemotron-3-Super-120B Q4 | Yes (78 to 86 GB) | Slow (15 to 20 tok/s) | Larger models. Wall clock roughly doubles. |

L6 note: record the GGUF file name and hash, the quant, the llama.cpp release tag and backend asset (ROCm vs Vulkan), the patched chat-template file hash, the kernel and ROCm/Mesa versions, the Claude Code version, and the BIOS/TTM memory split.

---

## 6. Open questions surfaced

1. **The box's OS.** The evidence favours Linux (Fedora 43+ or Ubuntu 26.04). On Windows, the WSL2 to host route and L7's `host.docker.internal` behaviour need checking.
2. **Claude Code version pinning in Harbor.** Does Harbor's `claude-code` adapter install a pinnable version? Any release can break the unsupported local route, and the same version must serve all three model tiers (L1).
3. **The chat-template patch as part of the "model".** A patched template changes what the model sees. Should L6 treat the template file as part of the model identity? (Proposed: yes.)
4. **Thinking on or off** for the local tier. This changes wall clock by about 2× and possibly the solve rate. Decide in #4.
5. **Background-model routing.** Should `ANTHROPIC_DEFAULT_HAIKU_MODEL` point at the same local model, which is the default and competes for the slot? Or should the server run with 2 slots?
6. **Port.** llama-server now defaults to 9931. The PRD's example `base_url` uses 4000 (a LiteLLM-style port). Update the PRD example once the server is chosen.

## Sources

- AMD, Strix Halo system optimisation (ROCm 10.1 develop docs): <https://rocmdocs.amd.com/en/develop/how-to/system-optimization/strixhalo.html>
- AMD, ROCm Core SDK 10.0.0 release notes: <https://rocm.docs.amd.com/en/develop/about/release-notes.html>
- AMD, HIP SDK for Windows system requirements: <https://rocm.docs.amd.com/projects/install-on-windows/en/latest/reference/system-requirements.html>
- Anthropic, Claude Code gateway compatibility guide: <https://code.claude.com/docs/en/llm-gateway-protocol>
- Anthropic, Claude Code "Other LLM gateways": <https://code.claude.com/docs/en/llm-gateway>
- llama.cpp server README (master, 2026-10-18): <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
- llama.cpp `server-chat.cpp` (Anthropic converter): <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-chat.cpp>
- llama.cpp release b11719 / v0.7.0: <https://github.com/ggml-org/llama.cpp/releases>
- HF blog, "New in llama.cpp: Anthropic Messages API" (2026-01-19): <https://huggingface.co/blog/ggml-org/anthropic-messages-api-in-llamacpp>
- Ollama, Anthropic compatibility: <https://docs.ollama.com/api/anthropic-compatibility>; Claude Code integration: <https://docs.ollama.com/integrations/claude-code>; GPU support: <https://docs.ollama.com/gpu>; source `anthropic/anthropic.go`: <https://github.com/ollama/ollama/blob/main/anthropic/anthropic.go>
- LM Studio, Claude Code integration: <https://lmstudio.ai/docs/integrations/claude-code>; Anthropic compat: <https://lmstudio.ai/docs/developer/anthropic-compat>
- LiteLLM, `/v1/messages`: <https://docs.litellm.ai/docs/anthropic_unified/>
- Issues: claude-code #77698, llama.cpp #27107, #22240, #20090, PRs #30608, #29482; vLLM #44000; Lemonade #2662; llama.cpp discussion #19467.
- kyuz0, Strix Halo toolboxes and results (`docs/results.json`, generated 2026-05-18): <https://github.com/kyuz0/amd-strix-halo-toolboxes>; vLLM toolboxes: <https://github.com/kyuz0/amd-strix-halo-vllm-toolboxes>
- Soothill, "llama.cpp: Vulkan vs ROCm on Strix Halo" (2026-08-03): <https://www.soothill.io/blog/2026/08/03/llamacpp-vulkan-vs-rocm-strix-halo/>; "Strix Halo benchmark: 23 coding deployments" (2026-08-14): <https://www.soothill.io/blog/2026/08/14/coding-model-benchmark-strix-halo/>
- hogeheer499, strix-halo-guide benchmarks: <https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md>
