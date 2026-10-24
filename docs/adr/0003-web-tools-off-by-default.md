# The web tools are off in every trial unless the job turns them on

`InstrumentedClaudeCode` disallows `WebFetch` and `WebSearch` in every trial. A job turns them back on with one agent kwarg, `allow_web: true`, and nothing else turns them on. We chose this because the task packs are Exercism exercises, and their reference solutions and tests are public. On the first smoke trial, Haiku fetched the solution (`.meta/proof.ci.ts`) with `WebFetch` and passed every reference test, so the reward measured a download, not the skill.

The class sets Harbor's `disable_web_search` option, which passes `--disallowedTools WebSearch,WebFetch` to Claude Code. That removes the tools from the agent's tool list, and it holds under `--permission-mode=bypassPermissions`, which Harbor uses. `allow_web` is the class's own kwarg, removed before Harbor reads the kwargs, so the job's `config.json` and the trial's `lock.json` record it.

## Considered Options

- **A `permissions.deny` rule in the merged settings**, like the instrument hooks: it works, but the agent still sees the tools, and every denied call is noise in the trajectory.
- **Let the variant's settings turn the tools on** (`permissions.allow`): a variant written for some other reason could turn the web on by accident. One named kwarg is easy to find in a job file.
- **Set `disable_web_search` in each job file**: no code, but one forgotten line contaminates a run again.
- **Cut the container's network**: Claude Code runs in the container and must reach the model API, so the network stays on.

## Consequences

`Bash` can still reach the web (`curl`, `wget`, `node -e "fetch(...)"`). Assay does not try to block that. Instead `assay trajectory` gives each trial a `web_access` mark (a web tool call that did not fail, or a `Bash` command with a URL, `curl`, `wget` or `git clone`), and `assay summary` keeps flagged trials but also gives its figures without them. The mark is a heuristic: it flags `curl localhost` and misses a fetch from a script. Changing `instruments/agent.py` changes the instruments digest, so trials run before this change fail the digest check against the new code.
