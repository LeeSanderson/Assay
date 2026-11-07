# The codebase ladder uses purpose-written codebases, built the same in TypeScript and Go, not real open-source projects

The upper rungs of `codebase-ladder` ask the agent to add a feature to a working codebase. We write those codebases ourselves: one order-and-inventory domain at two sizes, each built file for file the same in TypeScript and Go, with its own seed suite, feature specs, gold solutions and hidden reference tests. The TDD skill-transfer experiment that consumes the ladder's rungs is a crossover across the two languages, so each rung must hold the same task in both; and code that we write cannot be in any model's training data.

## Considered Options

- **Real open-source projects, one per language**: realistic code with real history, but no project exists the same in both languages, so a gap between languages would confound with a gap between codebases, and the code is likely in the training data of the models under test.
- **One real project, ported to the other language**: realistic on one side only, so the port is the artificial side and the language difference is built into the task.

## Consequences

The codebases are authoring work that we own, and a bad hidden test looks the same as a model failure. So every purpose-written task pack must pass five checks before the ladder runs it: the gold solution passes, the seed fails the feature tests, a blind solve by a model that is not a tier under test fails only tests that the Interface section states, the two languages hold the same test cases and the same seed design, and the owner reviews it. The realism of the rungs comes from layers and conventions, not from real-world history or dependencies: the codebases use only the existing toolchain images, with storage and I/O behind in-memory adapters.
