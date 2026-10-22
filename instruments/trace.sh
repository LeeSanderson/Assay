#!/usr/bin/env bash
# The trace hook: a measurement instrument (PRD section 5, "The trace hook").
#
# On each fire it compares the seed repository with the last snapshot in a
# separate git repository (trace.git), commits a new snapshot when something
# changed, and appends one line to trace.jsonl.
#
#   bash trace.sh          a PostToolUse or PostToolUseFailure fire; the hook
#                          input (JSON) comes on stdin
#   bash trace.sh seed     the seed fire, before the agent starts; no stdin
#
# ASSAY_TRACE_APP_DIR  the seed repository        (default /app)
# ASSAY_TRACE_DIR      where the trace is written  (default /logs/artifacts/trace)
#
# The hook is silent: it writes nothing to stdout and always exits 0.

APP_DIR="${ASSAY_TRACE_APP_DIR:-/app}"
TRACE_DIR="${ASSAY_TRACE_DIR:-/logs/artifacts/trace}"
JQ="$(dirname "${BASH_SOURCE[0]}")/jq"

TRACE_GIT="$TRACE_DIR/trace.git"
TRACE_JSONL="$TRACE_DIR/trace.jsonl"
ERRORS_LOG="$TRACE_DIR/errors.log"

# The hook's own git configuration: no system or global file, any owner,
# no line-ending or file-mode rewrites, and a fixed identity and date.
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_DIR="$TRACE_GIT"
export GIT_WORK_TREE="$APP_DIR"
export GIT_INDEX_FILE="$TRACE_GIT/index"
export GIT_AUTHOR_NAME="assay-trace" GIT_AUTHOR_EMAIL="trace@assay.invalid"
export GIT_COMMITTER_NAME="assay-trace" GIT_COMMITTER_EMAIL="trace@assay.invalid"
export GIT_AUTHOR_DATE="2000-01-01T00:00:00Z" GIT_COMMITTER_DATE="2000-01-01T00:00:00Z"
GIT_OPTS=(-c safe.directory='*' -c core.autocrlf=false -c core.safecrlf=false
          -c core.fileMode=false -c core.hooksPath=/dev/null)

tgit() { git "${GIT_OPTS[@]}" "$@"; }

# Set by fire(); read by append_line().
event="" tool_name="" tool_use_id="" changed="null" commit="" paths="[]" error=""

fail() {
    error="$1"
    changed="null" commit="" paths="[]"
    printf '%s %s seq=%s: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$seq" "$2" \
        >>"$ERRORS_LOG" 2>/dev/null
    return 1
}

read_input() {
    if [[ "${1:-}" == "seed" ]]; then
        event="seed"
        return 0
    fi
    local input fields
    input="$(cat)"
    fields="$(printf '%s' "$input" | "$JQ" -r \
        '[.hook_event_name // "", .tool_name // "", .tool_use_id // ""] | join("\u0001")' 2>&1)" \
        || { event="unknown"; fail "bad hook input" "jq: $fields"; return 1; }
    IFS=$'\x01' read -r event tool_name tool_use_id <<<"$fields"
}

snapshot() {
    local out
    if [[ ! -d "$TRACE_GIT" ]]; then
        out="$(tgit init -q 2>&1)" || { fail "git init failed" "$out"; return 1; }
    fi
    [[ -d "$APP_DIR" ]] || { fail "app folder missing" "no folder $APP_DIR"; return 1; }

    # -f stages files that any .gitignore hides; the pathspec leaves out
    # node_modules/ at any depth (git never descends into .git/).
    out="$(tgit add -A -f -- . ':(exclude,glob)**/node_modules/**' ':(exclude,glob)node_modules/**' 2>&1)" \
        || { fail "git add failed" "$out"; return 1; }

    local head="" base
    head="$(tgit rev-parse -q --verify HEAD 2>/dev/null)"
    base="${head:-$(tgit hash-object -t tree /dev/null)}"

    # -z output holds NUL bytes, which bash variables cannot, so it goes
    # straight into jq.
    paths="$(set -o pipefail
        tgit diff --cached --name-status --no-renames -z "$base" 2>&1 | "$JQ" -R -s -c \
        'split("\u0000") | map(select(. != "")) | [range(0; length; 2) as $i | {status: .[$i], path: .[$i + 1]}]' 2>&1)" \
        || { fail "git diff failed" "$paths"; return 1; }

    # The first fire always makes a snapshot, so the seed state exists.
    if [[ -n "$head" && "$paths" == "[]" ]]; then
        changed="false"
        return 0
    fi

    local tree parent=()
    tree="$(tgit write-tree 2>&1)" || { fail "git write-tree failed" "$tree"; return 1; }
    [[ -n "$head" ]] && parent=(-p "$head")
    commit="$(printf 'seq %s %s\n' "$seq" "$event" | tgit commit-tree "$tree" "${parent[@]}" 2>&1)" \
        || { fail "git commit failed" "$commit"; commit=""; return 1; }
    out="$(tgit update-ref HEAD "$commit" 2>&1)" \
        || { fail "git update-ref failed" "$out"; return 1; }
    changed="true"
}

append_line() {
    local ts line
    ts="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
    line="$("$JQ" -n -c \
        --argjson seq "$seq" --arg ts "$ts" --arg event "$event" \
        --arg tool_name "$tool_name" --arg tool_use_id "$tool_use_id" \
        --argjson changed "$changed" --arg commit "$commit" \
        --argjson paths "$paths" --arg error "$error" \
        '{seq: $seq, ts: $ts, event: $event,
          tool_name: (if $tool_name == "" then null else $tool_name end),
          tool_use_id: (if $tool_use_id == "" then null else $tool_use_id end),
          changed: $changed}
         + (if $changed == true then {commit: $commit} else {} end)
         + {paths: $paths}
         + (if $error != "" then {error: $error} else {} end)' 2>>"$ERRORS_LOG")" \
        || line="{\"seq\":$seq,\"ts\":\"$ts\",\"changed\":null,\"paths\":[],\"error\":\"jq failed\"}"
    printf '%s\n' "$line" >>"$TRACE_JSONL"
}

fire() {
    mkdir -p "$TRACE_DIR" || return 0
    # Harbor keeps the execute bit only if the host file has it.
    [[ -x "$JQ" ]] || chmod +x "$JQ" 2>/dev/null
    seq=0
    [[ -f "$TRACE_JSONL" ]] && seq="$(wc -l <"$TRACE_JSONL" | tr -d ' ')"
    read_input "$@" && snapshot
    append_line
}

main() {
    # Fires for parallel tool calls must not interleave.
    if command -v flock >/dev/null && mkdir -p "$TRACE_DIR" 2>/dev/null; then
        exec 9>>"$TRACE_DIR/.lock" && flock -w 9 9
    fi
    fire "$@"
}

main "$@" >/dev/null 2>&1
exit 0
