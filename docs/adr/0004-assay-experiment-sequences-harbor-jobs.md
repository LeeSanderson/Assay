# `assay experiment` runs the Harbor jobs of an experiment one after another, and Harbor still runs every trial

An experiment needs more than one Harbor job: Harbor sets extra instructions per job, so two conditions are two jobs, and a harness or setup change can split them further. `uv run assay experiment` therefore runs each job of the experiment in turn through the `assay run` path (ADR 0002), then runs the experiment's evaluations and its summary. Assay never drives an agent and never schedules trials inside a job: concurrency inside a job stays with Harbor. This redraws the old line "Assay is not a runner, no execution or scheduler code" as "Assay re-implements nothing Harbor provides; if it does, that is a defect".

## Considered Options

- **One Harbor job per experiment**: no sequencing code, but Harbor cannot give each condition its own extra instructions inside one job, and agents with different setups in one job are not tested.
- **The user runs each job by hand, then the analysis**: the Phase 0 way. It does not scale past a few jobs, and it gives no resume across the jobs and the evaluations.
- **Run the jobs in parallel**: faster for hosted tiers, but the local tier is bound by one host and the hosted tiers by rate limits. Parallel jobs can come later if the wall clock becomes the constraint.

## Consequences

The 400 to 600 line budget for the analyzer and success criterion 5 ("no execution, sandbox or scheduler code") are replaced by the rule above. Resume of a job still depends on Harbor's own resume, which matches trials by exact config, so the experiment references committed job files and never generates them.
