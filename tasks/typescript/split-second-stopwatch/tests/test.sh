#!/usr/bin/env bash
# The verifier of the TypeScript split-second-stopwatch task pack.
#
# Two passes, each on a scratch copy of the repository, so the repository
# itself never changes:
#   1. The outcome pass removes each test file of the agent, adds the reference
#      tests, type-checks them and the files they import (`tsc`, because
#      babel-jest does not), and runs the reference tests.
#   2. The agent pass runs the tests of the agent on the repository as it is.
#      Skipped tests count in the total but not as passed. With no agent
#      tests, agent_tests_compile says whether the code builds. Agent tests
#      compile only if tsc passes and every suite loads; if they do not,
#      agent_tests_passed is 0 and agent_tests_total is at least the number
#      of agent test files.
# It always writes one reward.json with seven numeric fields. It uses no
# network, so replay runs it without change on each trace snapshot.

set -u

APP_DIR=${ASSAY_APP_DIR:-/app}
OUT_DIR=${ASSAY_VERIFIER_DIR:-/logs/verifier}
TESTS_DIR=$(cd "$(dirname "$0")" && pwd)
REFERENCE_TEST=assay-reference.split-second-stopwatch.test.ts
# Each step has its own limit, so both passes fit in the 600 s verifier timeout.
TSC_TIMEOUT=120
JEST_TIMEOUT=150

export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
mkdir -p "$OUT_DIR"
WORK=$(mktemp -d)
# Yarn PnP finds the global cache by a path relative to the project, so each
# scratch copy sits beside the repository, at the same depth.
OUTCOME=$(mktemp -d "$(dirname "$APP_DIR")/.assay-outcome.XXXXXX")
AGENT=$(mktemp -d "$(dirname "$APP_DIR")/.assay-agent.XXXXXX")
trap 'rm -rf "$WORK" "$OUTCOME" "$AGENT"' EXIT

# The test-file class. It must equal `test_files` for typescript in
# analyze/languages.py; tests/test_test_file_patterns.py checks it.
TEST_FILE_PATTERNS=('*.test.ts' '*.spec.ts')
name_tests=()
for pattern in "${TEST_FILE_PATTERNS[@]}"; do name_tests+=(-o -name "$pattern"); done
name_tests=("${name_tests[@]:1}")

agent_test_files() {
    (cd "$1" && find . \( -name .git -o -name node_modules -o -name .yarn \) -prune \
        -o -type f \( "${name_tests[@]}" \) -print | sed 's|^\./||' | sort)
}

copy_repository() {
    (cd "$1" && tar --exclude=./.git -cf - .) | (cd "$2" && tar -xf -)
}

# typecheck <dir> <tsconfig> <log>: prints 1 when tsc passes, else 0.
typecheck() {
    if (cd "$1" && timeout "$TSC_TIMEOUT" corepack yarn tsc --noEmit -p "$2") >"$3" 2>&1; then echo 1; else echo 0; fi
}

# jest_counts <json>: prints "<passed> <total> <suites that failed to load>"
# from a Jest --json file.
jest_counts() {
    node -e '
        let r = {};
        try { r = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); } catch {}
        console.log(`${r.numPassedTests || 0} ${r.numTotalTests || 0} ${r.numRuntimeErrorTestSuites || 0}`);
    ' "$1"
}

# --- 1. The outcome pass ------------------------------------------------------
copy_repository "$APP_DIR" "$OUTCOME"
agent_test_files "$OUTCOME" | (cd "$OUTCOME" && xargs -r -d '\n' rm -f --)
cp "$TESTS_DIR/$REFERENCE_TEST" "$OUTCOME/"

# Type-check the reference test and the files it imports only, so a type error
# in a file the reference tests never load does not zero the reward.
printf '{"extends": "./tsconfig.json", "files": ["%s"], "include": []}\n' "$REFERENCE_TEST" \
    >"$OUTCOME/tsconfig.assay-outcome.json"
reference_compiles=$(typecheck "$OUTCOME" tsconfig.assay-outcome.json "$OUT_DIR/outcome-tsc.log")
(cd "$OUTCOME" && timeout "$JEST_TIMEOUT" corepack yarn jest --ci --no-cache --json --outputFile="$WORK/outcome.json" \
    --runTestsByPath "./$REFERENCE_TEST") >"$OUT_DIR/outcome-jest.log" 2>&1
read -r reference_passed reference_total _ < <(jest_counts "$WORK/outcome.json")

reward=0
if [ "$reference_compiles" = 1 ] && [ "$reference_total" -gt 0 ] \
    && [ "$reference_passed" = "$reference_total" ]; then
    reward=1
fi

# --- 2. The agent pass --------------------------------------------------------
copy_repository "$APP_DIR" "$AGENT"
mapfile -t agent_tests < <(agent_test_files "$AGENT")

agent_tests_passed=0
agent_tests_total=0
if [ "${#agent_tests[@]}" -eq 0 ]; then
    # No tests: agent_tests_compile says whether the code builds.
    agent_tests_compile=$(typecheck "$AGENT" tsconfig.json "$OUT_DIR/agent-tsc.log")
else
    # The project's tsconfig.json covers top-level files only; add each test file.
    node -e '
        const files = process.argv.slice(2);
        require("fs").writeFileSync(process.argv[1],
            JSON.stringify({ extends: "./tsconfig.json", files }));
    ' "$AGENT/tsconfig.assay-agent-tests.json" "${agent_tests[@]}"
    agent_tests_compile=$(typecheck "$AGENT" tsconfig.assay-agent-tests.json "$OUT_DIR/agent-tsc.log")
    (cd "$AGENT" && timeout "$JEST_TIMEOUT" corepack yarn jest --ci --no-cache --json --outputFile="$WORK/agent.json" \
        --passWithNoTests --testMatch "${TEST_FILE_PATTERNS[@]/#/**/}") >"$OUT_DIR/agent-jest.log" 2>&1
    read -r agent_tests_passed agent_tests_total load_errors < <(jest_counts "$WORK/agent.json")
    # A suite that throws while it loads does not compile.
    if [ "$load_errors" -gt 0 ]; then
        agent_tests_compile=0
    fi
    # Red-compile rule (same in every pack): when agent test files exist but do
    # not compile, no test passes and agent_tests_total is at least the number
    # of agent test files, so replay labels the snapshot red-compile and not
    # no-tests. A suite that fails to load drops out of Jest's total.
    if [ "$agent_tests_compile" = 0 ]; then
        agent_tests_passed=0
        if [ "$agent_tests_total" -lt "${#agent_tests[@]}" ]; then
            agent_tests_total=${#agent_tests[@]}
        fi
    fi
fi

cat >"$OUT_DIR/reward.json" <<EOF
{"reward": $reward, "reference_compiles": $reference_compiles, "reference_passed": $reference_passed, "reference_total": $reference_total, "agent_tests_compile": $agent_tests_compile, "agent_tests_passed": $agent_tests_passed, "agent_tests_total": $agent_tests_total}
EOF
cat "$OUT_DIR/reward.json"
