# Measurement instruments reach the container through a custom agent class, not through the variant bundle

Every Assay job runs `instruments.agent:InstrumentedClaudeCode`, a small subclass of Harbor's `claude-code` agent, which uploads `instruments/` to `/harbor/instruments/`, merges the instrument hooks into the variant's settings, takes the seed snapshot, and writes a digest to `/logs/artifacts/trace/instruments.json`. We chose this over the PRD's skill-directory route because Harbor requires a `SKILL.md` in every `--skill` directory, so the instrument would appear as a skill in every condition, including the control. Keeping instruments out of `--skill` and out of the variant's settings object also means bundle digests and comparability rules cover only the artifact under test.

## Considered Options

- **Inline hook command in the settings object**: no file needed, but one escaped blob per hook does not scale to several or complex instruments.
- **Hidden instrument skill** (`disable-model-invocation: true`): keeps the description out of context, but its frontmatter hooks never register in a headless run, and the instrument still travels inside the bundle.
- **Harbor `environment.mounts`**: native and needs no code, but the lock records no content digest, and the hook declarations would still be merged into each variant's settings.
- **Baked into each task image**: couples every task pack to the instruments; a hook change rebuilds every image.

## Consequences

The subclass is coupled to Harbor internals (`setup()`, `upload_dir`), so the Harbor version pin matters more. Harbor records only the class's import path, so `instruments.json` carries our own digest of `instruments/` (which includes the class). Because the class runs in Harbor's process, it also gives a local model a zero price in LiteLLM's price table, which is global to that process, so that Harbor's per-step cost estimate succeeds (issue #33). That couples it to `model_connection` and to how `_estimate_step_costs` prices a step too.
