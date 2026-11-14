#!/bin/bash
# Assay verifier for the Go two-bucket task pack (PRD section 6, "Task packs").
#
# The seed suite is the tests that the seed holds before the agent starts.
# tests/seed-suite/ holds a copy of it in its seed form, at the same paths, and
# tests/seed-suite-tests the number of its tests; a pack with no seed suite
# holds neither. An agent test is a test file that the copy does not hold, or
# whose content differs from the copy's (PRD section 20, "The pack recipe").
#
# 1. Outcome pass: copy the repository to a scratch directory, remove every
#    test file (`*_test.go`), restore the seed suite from the copy, add the
#    reference tests, and run the packages that hold them, so both compile
#    together with the agent's code. A test whose top-level function a
#    reference file declares counts in reference_*; any other in seed_suite_*.
#    A seed suite that does not compile passes none of its recorded tests.
#    When a package does not build, the reference tests run again on their
#    own, without the seed suite, for reference_*: the build failure may be
#    the seed suite's alone.
# 2. Agent pass: in a second scratch copy, remove each seed test file that the
#    agent did not change, and run the agent's tests. If agent test files
#    exist but do not compile, agent_tests_passed is 0 and agent_tests_total
#    is at least the number of agent test files.
#
# The reward is 1 only when each reference test and each seed-suite test
# passes. Both passes go into one reward.json with nine numeric fields. The
# script always writes that file, whatever happens to the passes.
set -u

APP=${ASSAY_APP_DIR:-/app}
HERE="$(cd "$(dirname "$0")" && pwd)"
SEED_SUITE="$HERE/seed-suite"
SEED_SUITE_TESTS="$HERE/seed-suite-tests"
OUT=${ASSAY_VERIFIER_DIR:-/logs/verifier}
PASS_TIMEOUT=240s

mkdir -p "$OUT"

# The test-file class. It must equal `test_files` for go in
# analyze/languages.py; tests/test_test_file_patterns.py checks it.
TEST_FILE_PATTERNS=('*_test.go')
name_tests=()
for pattern in "${TEST_FILE_PATTERNS[@]}"; do name_tests+=(-o -name "$pattern"); done
name_tests=("${name_tests[@]:1}")

write_reward() {
  printf '{"reward": %d, "reference_compiles": %d, "reference_passed": %d, "reference_total": %d, "agent_tests_compile": %d, "agent_tests_passed": %d, "agent_tests_total": %d, "seed_suite_passed": %d, "seed_suite_total": %d}\n' \
    "$reward" "$reference_compiles" "$reference_passed" "$reference_total" \
    "$agent_tests_compile" "$agent_tests_passed" "$agent_tests_total" \
    "$seed_suite_passed" "$seed_suite_total" > "$OUT/reward.json"
}

reward=0 reference_compiles=0 reference_passed=0 reference_total=0
agent_tests_compile=0 agent_tests_passed=0 agent_tests_total=0
seed_suite_passed=0 seed_suite_total=0
write_reward

# seed_suite_files: the files of the seed-suite copy, as relative paths.
seed_suite_files() {
  if [ -d "$SEED_SUITE" ]; then
    (cd "$SEED_SUITE" && find . -type f -print | sed 's|^\./||' | sort)
  fi
}

copy_repository() {
  (cd "$1" && tar --exclude=./.git -cf - .) | (cd "$2" && tar -xf -)
}

# run_go_tests <dir> <json file> <package pattern>...
# Sets: compiles (1/0), passed, total (leaf tests; a skipped test counts in
# total only) for the tests whose top-level function is in $reference_names,
# and other_passed, other_total for the rest.
reference_names=""
run_go_tests() {
  local dir="$1" json="$2" rc counts
  shift 2
  (cd "$dir" && go test -json -count=1 -timeout "$PASS_TIMEOUT" "$@") > "$json" 2> "$json.stderr"
  rc=$?
  compiles=1
  if grep -q -e '"Action":"build-fail"' -e '"FailedBuild"' "$json"; then
    compiles=0
  elif [ "$rc" -ne 0 ] && ! grep -q '"Action":"start"' "$json"; then
    compiles=0 # go itself failed before running any package (for example a broken go.mod)
  fi
  counts=$(awk -v refs="$reference_names" '
    function field(name,   m) {
      if (match($0, "\"" name "\":\"([^\"\\\\]|\\\\.)*\"")) {
        m = substr($0, RSTART, RLENGTH)
        return substr(m, length(name) + 5, length(m) - length(name) - 5)
      }
      return ""
    }
    BEGIN { n = split(refs, list, " "); for (i = 1; i <= n; i++) reference[list[i]] = 1 }
    /"Test":/ && /"Action":"(pass|fail|skip)"/ {
      key = field("Package") "\t" field("Test")
      status[key] = field("Action")
    }
    END {
      passed = 0; total = 0; other_passed = 0; other_total = 0
      for (k in status) {
        leaf = 1
        for (other in status) {
          if (index(other, k "/") == 1) { leaf = 0; break }
        }
        if (!leaf) continue
        top = substr(k, index(k, "\t") + 1)
        sub(/\/.*/, "", top)
        if (top in reference) { total++; if (status[k] == "pass") passed++ }
        else { other_total++; if (status[k] == "pass") other_passed++ }
      }
      print passed, total, other_passed, other_total
    }' "$json")
  read -r passed total other_passed other_total <<< "$counts"
}

mapfile -t seed_tests < <(seed_suite_files)
# The tests of the seed suite, as go test counts them: the recorded number, or
# one for each file when none is recorded.
seed_suite_count=${#seed_tests[@]}
if [ -f "$SEED_SUITE_TESTS" ]; then seed_suite_count=$(tr -dc '0-9' < "$SEED_SUITE_TESTS"); fi

# --- 1. Outcome pass -------------------------------------------------------
scratch="$(mktemp -d)"
copy_repository "$APP" "$scratch"
find "$scratch" -type f \( "${name_tests[@]}" \) -delete
if [ "${#seed_tests[@]}" -gt 0 ]; then
  cp -r "$SEED_SUITE/." "$scratch"/
fi
cp -r "$HERE"/reference/. "$scratch"/
mapfile -t reference_files < <(cd "$HERE/reference" && find . -type f -print | sed 's|^\./||')
reference_names=$(cd "$HERE/reference" \
  && sed -En 's/^func ((Test|Example|Fuzz)[A-Za-z0-9_]*)\(.*/\1/p' "${reference_files[@]}" | tr '\n' ' ')
# packages_of <file>...: the packages that hold the files.
packages_of() {
  for f in "$@"; do d=$(dirname "$f"); [ "$d" = . ] && echo . || echo "./$d"; done | sort -u
}
mapfile -t packages < <(packages_of "${reference_files[@]}" "${seed_tests[@]}")

run_go_tests "$scratch" "$OUT/outcome.json" "${packages[@]}"
reference_compiles=$compiles
reference_passed=$passed
reference_total=$total
seed_suite_passed=$other_passed
seed_suite_total=$other_total
# A seed suite that does not compile, or does not run, passes no test, and
# counts each of its tests.
if [ "$compiles" -eq 0 ] || [ "$seed_suite_total" -lt "$seed_suite_count" ]; then
  seed_suite_passed=0
  if [ "$seed_suite_total" -lt "$seed_suite_count" ]; then
    seed_suite_total=$seed_suite_count
  fi
fi
# Whether the reference tests compile does not depend on the seed suite.
if [ "$compiles" -eq 0 ] && [ "${#seed_tests[@]}" -gt 0 ]; then
  alone="$(mktemp -d)"
  copy_repository "$APP" "$alone"
  find "$alone" -type f \( "${name_tests[@]}" \) -delete
  cp -r "$HERE"/reference/. "$alone"/
  mapfile -t reference_packages < <(packages_of "${reference_files[@]}")
  run_go_tests "$alone" "$OUT/reference.json" "${reference_packages[@]}"
  reference_compiles=$compiles
  reference_passed=$passed
  reference_total=$total
  rm -rf "$alone"
fi
if [ "$reference_compiles" -eq 1 ] && [ "$reference_total" -gt 0 ] \
   && [ "$reference_passed" -eq "$reference_total" ] \
   && [ "$seed_suite_passed" -eq "$seed_suite_total" ]; then
  reward=1
fi
rm -rf "$scratch"
write_reward

# --- 2. Agent pass ---------------------------------------------------------
scratch="$(mktemp -d)"
copy_repository "$APP" "$scratch"
for seed_test in "${seed_tests[@]}"; do
  if cmp -s "$SEED_SUITE/$seed_test" "$scratch/$seed_test"; then rm -f "$scratch/$seed_test"; fi
done
reference_names=""
run_go_tests "$scratch" "$OUT/agent.json" ./...
agent_tests_compile=$compiles
agent_tests_passed=$other_passed
agent_tests_total=$other_total
# Red-compile rule (same in every pack): when agent test files exist but do not
# compile, no test passes and agent_tests_total is at least the number of agent
# test files, so replay labels the snapshot red-compile and not no-tests.
# A build failure emits no test events, so the counted total is often 0.
if [ "$agent_tests_compile" -eq 0 ]; then
  agent_test_files=$(cd "$scratch" && find . -type f \( "${name_tests[@]}" \) -print | wc -l)
  if [ "$agent_test_files" -gt 0 ]; then
    agent_tests_passed=0
    if [ "$agent_tests_total" -lt "$agent_test_files" ]; then
      agent_tests_total=$agent_test_files
    fi
  fi
fi
rm -rf "$scratch"
write_reward

cat "$OUT/reward.json"
exit 0
