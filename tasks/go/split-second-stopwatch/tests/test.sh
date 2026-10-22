#!/bin/bash
# Assay verifier for the Go split-second-stopwatch task pack (PRD §5 "Task packs").
#
# 1. Outcome pass: copy the repository to a scratch directory, remove every
#    agent test file (`*_test.go`), add the reference tests, and run them.
# 2. Agent pass: run the agent's tests in the repository without change.
#
# Both passes go into one /logs/verifier/reward.json with seven numeric fields.
# The script always writes that file, whatever happens to the passes.
set -u

APP=/app
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT=/logs/verifier
PASS_TIMEOUT=240s

mkdir -p "$OUT"

write_reward() {
  printf '{"reward": %d, "reference_compiles": %d, "reference_passed": %d, "reference_total": %d, "agent_tests_compile": %d, "agent_tests_passed": %d, "agent_tests_total": %d}\n' \
    "$reward" "$reference_compiles" "$reference_passed" "$reference_total" \
    "$agent_tests_compile" "$agent_tests_passed" "$agent_tests_total" > "$OUT/reward.json"
}

reward=0 reference_compiles=0 reference_passed=0 reference_total=0
agent_tests_compile=0 agent_tests_passed=0 agent_tests_total=0
write_reward

# run_go_tests <dir> <package pattern> <json file>
# Sets: compiles (1/0), passed, total (leaf tests; a skipped test counts in total only).
run_go_tests() {
  local dir="$1" pattern="$2" json="$3" rc counts
  (cd "$dir" && go test -json -count=1 -timeout "$PASS_TIMEOUT" "$pattern") > "$json" 2> "$json.stderr"
  rc=$?
  compiles=1
  if grep -q -e '"Action":"build-fail"' -e '"FailedBuild"' "$json"; then
    compiles=0
  elif [ "$rc" -ne 0 ] && ! grep -q '"Action":"start"' "$json"; then
    compiles=0 # go itself failed before running any package (for example a broken go.mod)
  fi
  counts=$(awk '
    function field(name,   m) {
      if (match($0, "\"" name "\":\"([^\"\\\\]|\\\\.)*\"")) {
        m = substr($0, RSTART, RLENGTH)
        return substr(m, length(name) + 5, length(m) - length(name) - 5)
      }
      return ""
    }
    /"Test":/ && /"Action":"(pass|fail|skip)"/ {
      key = field("Package") "\t" field("Test")
      status[key] = field("Action")
    }
    END {
      passed = 0; total = 0
      for (k in status) {
        leaf = 1
        for (other in status) {
          if (index(other, k "/") == 1) { leaf = 0; break }
        }
        if (leaf) { total++; if (status[k] == "pass") passed++ }
      }
      print passed, total
    }' "$json")
  passed=${counts% *}
  total=${counts#* }
}

# --- 1. Outcome pass -------------------------------------------------------
scratch="$(mktemp -d)"
(cd "$APP" && tar --exclude=./.git -cf - .) | (cd "$scratch" && tar -xf -)
find "$scratch" -name '*_test.go' -type f -delete
cp "$HERE"/reference/assay_reference_*_test.go "$scratch"/

run_go_tests "$scratch" . "$OUT/outcome.json"
reference_compiles=$compiles
reference_passed=$passed
reference_total=$total
if [ "$reference_compiles" -eq 1 ] && [ "$reference_total" -gt 0 ] \
   && [ "$reference_passed" -eq "$reference_total" ]; then
  reward=1
fi
rm -rf "$scratch"
write_reward

# --- 2. Agent pass ---------------------------------------------------------
run_go_tests "$APP" ./... "$OUT/agent.json"
agent_tests_compile=$compiles
agent_tests_passed=$passed
agent_tests_total=$total
write_reward

cat "$OUT/reward.json"
exit 0
