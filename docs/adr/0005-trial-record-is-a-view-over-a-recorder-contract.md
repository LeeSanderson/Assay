# The trial record is a view that a per-harness reader builds over a shared recorder contract, not a file Assay writes

Every harness's recorder writes the same trace folder (`trace.jsonl`, `trace.git` from seed to a `final` snapshot taken after the agent exits, and `instruments.json` with its granularity and whether one step's calls may overlap). A reader for each harness then builds the trial record in memory from that folder and Harbor's trial folder: steps with their tokens and cost, tool calls with a verbatim name and arguments plus a `kind`, and the history joined to the calls. Assay writes no normalized copy, so there is nothing to keep in step with its sources; the record's digest for resume is the digest of the files it reads. No evaluation reads the raw Harbor folder: a fact an evaluation needs becomes a record field, which a reader fills or marks absent.

## Considered Options

- **A normalized file per trial**: readable with `jq` and without Assay, but a second copy that can go stale, with its own resume and invalidation, and the per-harness work still has to happen somewhere.
- **A documented set of paths over Harbor's tree, read directly by evaluations**: no reader code, but every evaluation would parse ATIF and each harness's quirks itself, and so would be harness-specific without saying so.

## Consequences

The record exists only through Assay's Python code; an evaluation in a container gets checkouts and files, not the record. Adding a harness means a recorder that writes the trace folder plus a reader. The required core (every tool call in order, failed ones included; the history and its granularity; token, cost and time totals; identity; versions) must be complete for every harness, so opencode's recorder must recover the failed calls its ATIF and hook lose. Optional parts (result, error flag, exit code, per-call time, per-step cost) may be absent, and Assay refuses before any job runs an experiment whose evaluation needs a part its harness cannot give.
