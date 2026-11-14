#!/usr/bin/env bash
# The verifier of the TypeScript wordy task pack.
#
# The seed suite is the tests that the seed holds before the agent starts.
# tests/seed-suite/ holds a copy of it in its seed form, at the same paths; a
# pack with no seed suite holds no copy. An agent test is a test file that the
# copy does not hold, or whose content differs from the copy's (PRD section 20,
# "The pack recipe").
#
# Two passes, each on a scratch copy of the repository, so the repository
# itself never changes:
#   1. The outcome pass removes each test file, restores the seed suite from
#      the copy, adds the reference tests, type-checks the reference tests and
#      the seed suite with the files they import (`tsc`, because babel-jest
#      does not), and runs both. reference_* counts the reference tests and
#      seed_suite_* the seed suite. A seed suite that does not type-check, or
#      a seed test file that does not load, passes no test.
#   2. The agent pass removes each seed test file that the agent did not
#      change and runs the agent tests. Skipped tests count in the total but
#      not as passed. With no agent tests, agent_tests_compile says whether
#      the code builds. Agent tests compile only if tsc passes and every suite
#      loads; if they do not, agent_tests_passed is 0 and agent_tests_total is
#      at least the number of agent test files.
# The reward is 1 only when each reference test and each seed-suite test
# passes. It always writes one reward.json with nine numeric fields. It uses
# no network, so replay runs it without change on each trace snapshot.

set -u

APP_DIR=${ASSAY_APP_DIR:-/app}
OUT_DIR=${ASSAY_VERIFIER_DIR:-/logs/verifier}
TESTS_DIR=$(cd "$(dirname "$0")" && pwd)
SEED_SUITE="$TESTS_DIR/seed-suite"
REFERENCE_TEST=assay-reference.wordy.test.ts
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

# test_files <dir>: the test files under dir, as relative paths.
test_files() {
    (cd "$1" && find . \( -name .git -o -name node_modules -o -name .yarn \) -prune \
        -o -type f \( "${name_tests[@]}" \) -print | sed 's|^\./||' | sort)
}

# seed_suite_files: the files of the seed-suite copy, as relative paths.
seed_suite_files() {
    if [ -d "$SEED_SUITE" ]; then
        (cd "$SEED_SUITE" && find . -type f -print | sed 's|^\./||' | sort)
    fi
}

copy_repository() {
    (cd "$1" && tar --exclude=./.git -cf - .) | (cd "$2" && tar -xf -)
}

# typecheck <dir> <tsconfig> <log>: prints 1 when tsc passes, else 0.
typecheck() {
    if (cd "$1" && timeout "$TSC_TIMEOUT" corepack yarn tsc --noEmit -p "$2") >"$3" 2>&1; then echo 1; else echo 0; fi
}

# tsconfig_for <file> <test file>...: writes a tsconfig that type-checks only
# the given test files and the files they import.
tsconfig_for() {
    node -e '
        const files = process.argv.slice(2);
        require("fs").writeFileSync(process.argv[1],
            JSON.stringify({ extends: "./tsconfig.json", files, include: [] }));
    ' "$@"
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

# outcome_counts <json>: prints "<reference passed> <reference total> <seed
# passed> <seed total> <seed suites that failed to load>" from a Jest --json
# file, by test file: the reference test file, or any other (the seed suite).
outcome_counts() {
    node -e '
        let r = {};
        try { r = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); } catch {}
        const c = { ref: [0, 0], seed: [0, 0] };
        let seedLoadErrors = 0;
        for (const file of r.testResults || []) {
            const side = require("path").basename(file.name) === process.argv[2] ? "ref" : "seed";
            const tests = file.assertionResults || [];
            if (side === "seed" && file.status === "failed" && tests.length === 0) seedLoadErrors++;
            c[side][0] += tests.filter((t) => t.status === "passed").length;
            c[side][1] += tests.length;
        }
        console.log(`${c.ref[0]} ${c.ref[1]} ${c.seed[0]} ${c.seed[1]} ${seedLoadErrors}`);
    ' "$1" "$REFERENCE_TEST"
}

mapfile -t seed_tests < <(seed_suite_files)

# --- 1. The outcome pass ------------------------------------------------------
copy_repository "$APP_DIR" "$OUTCOME"
test_files "$OUTCOME" | (cd "$OUTCOME" && xargs -r -d '\n' rm -f --)
if [ "${#seed_tests[@]}" -gt 0 ]; then
    cp -r "$SEED_SUITE/." "$OUTCOME/"
fi
cp "$TESTS_DIR/$REFERENCE_TEST" "$OUTCOME/"

# Type-check the reference test and the files it imports only, so a type error
# in a file the reference tests never load does not zero the reward.
tsconfig_for "$OUTCOME/tsconfig.assay-outcome.json" "$REFERENCE_TEST"
reference_compiles=$(typecheck "$OUTCOME" tsconfig.assay-outcome.json "$OUT_DIR/outcome-tsc.log")
seed_suite_compiles=1
if [ "${#seed_tests[@]}" -gt 0 ]; then
    tsconfig_for "$OUTCOME/tsconfig.assay-seed-suite.json" "${seed_tests[@]}"
    seed_suite_compiles=$(typecheck "$OUTCOME" tsconfig.assay-seed-suite.json "$OUT_DIR/seed-suite-tsc.log")
fi
(cd "$OUTCOME" && timeout "$JEST_TIMEOUT" corepack yarn jest --ci --no-cache --json --outputFile="$WORK/outcome.json" \
    --runTestsByPath "./$REFERENCE_TEST" "${seed_tests[@]/#/./}") >"$OUT_DIR/outcome-jest.log" 2>&1
read -r reference_passed reference_total seed_suite_passed seed_suite_total seed_load_errors \
    < <(outcome_counts "$WORK/outcome.json")
# A seed suite that does not compile, or does not run, passes no test, and
# each of its files counts: each file of a seed suite that runs holds a test.
if [ "$seed_suite_compiles" = 0 ] || [ "$seed_load_errors" -gt 0 ] \
    || [ "$seed_suite_total" -lt "${#seed_tests[@]}" ]; then
    seed_suite_passed=0
    if [ "$seed_suite_total" -lt "${#seed_tests[@]}" ]; then
        seed_suite_total=${#seed_tests[@]}
    fi
fi

reward=0
if [ "$reference_compiles" = 1 ] && [ "$reference_total" -gt 0 ] \
    && [ "$reference_passed" = "$reference_total" ] \
    && [ "$seed_suite_passed" = "$seed_suite_total" ]; then
    reward=1
fi

# --- 2. The agent pass --------------------------------------------------------
copy_repository "$APP_DIR" "$AGENT"
for seed_test in "${seed_tests[@]}"; do
    if cmp -s "$SEED_SUITE/$seed_test" "$AGENT/$seed_test"; then rm -f "$AGENT/$seed_test"; fi
done
mapfile -t agent_tests < <(test_files "$AGENT")

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
{"reward": $reward, "reference_compiles": $reference_compiles, "reference_passed": $reference_passed, "reference_total": $reference_total, "agent_tests_compile": $agent_tests_compile, "agent_tests_passed": $agent_tests_passed, "agent_tests_total": $agent_tests_total, "seed_suite_passed": $seed_suite_passed, "seed_suite_total": $seed_suite_total}
EOF
cat "$OUT_DIR/reward.json"
