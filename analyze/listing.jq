# The neutral listing of one trial, for the person check (PRD section 5,
# "How a person checks trajectory.py"). It is kept separate from
# trajectory.py on purpose: it gives no class, no seen state, no verdict
# and no count. Run it from the repository root:
#
#   jq -r `
#     --slurpfile trace   <trial>\artifacts\logs\artifacts\trace\trace.jsonl `
#     --slurpfile replay  analysis\<job-id>\<trial>\replay.jsonl `
#     --slurpfile runs    analysis\<job-id>\<trial>\agent-runs.jsonl `
#     -f analyze\listing.jq <trial>\agent\trajectory.json
#
# (PowerShell; README.md, "Stage 5", has a loop over every trial of a job.)
#
# One line for each tool call, in ATIF order:
#
#   <step_id>.<position>  <function_name>  "<path or command>"  paths=[<status> <path>, ...]
#     then, for a test run of the agent:          partial=<bool> exit_code=<n>
#     then, for a call that made a snapshot:      test_state=<state> agent_tests_total=<n>
#                                                 (or replay_error=<error>)
#
# paths=- means the call has no trace line. A first "seed" line gives the
# seed snapshot.

def target:
  .arguments // {}
  | (.file_path // .notebook_path // .command // .pattern // .path // .url) as $t
  | if $t == null then "-" else ($t | tojson) end;

def trace_paths($lines):
  if ($lines | length) == 0 then "paths=-"
  else "paths=[" + ([$lines[] | (.paths // [])[] | "\(.status) \(.path)"] | join(", ")) + "]"
  end;

def test_run($id):
  [$runs[] | select(.tool_use_id == $id) | "partial=\(.partial) exit_code=\(.exit_code)"];

def snapshot($id):
  [$replay[] | select(.tool_use_id == $id)
   | if .error then "replay_error=\(.error)"
     else "test_state=\(.test_state) agent_tests_total=\(.agent_tests_total)" end];

def fields: map(select(. != "")) | join("  ");

( [$trace[] | select(.event == "seed")]
  | select(length > 0)
  | ["seed", trace_paths(.)] + snapshot(null)
  | fields ),
( .steps | sort_by(.step_id)[]
  | .step_id as $step
  | (.tool_calls // []) | to_entries[]
  | .key as $position
  | .value
  | .tool_call_id as $id
  | ["\($step).\($position)", .function_name, target,
     trace_paths([$trace[] | select(.tool_use_id == $id)])]
    + test_run($id) + snapshot($id)
  | fields )
