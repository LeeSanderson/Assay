# Quality and security scanners over a repository snapshot

Research for [issue #47](https://github.com/LeeSanderson/Assay/issues/47), part of the experiment-platform map ([issue #44](https://github.com/LeeSanderson/Assay/issues/44)).
Date: 2026-10-26.

Question: how can code-quality and security scanners run **offline, after the trial, over one repository snapshot** (seed or final) in TypeScript and Go, and what do they output? The goal is to know what a `sonar`- or `semgrep`-style built-in **evaluation** would consume and produce, not to choose a tool.

## Sources and trust

Every claim below names its source. "Docs" means the tool's official documentation or README; links are inline.
**Nothing here was run.** Runtime figures are marked *unconfirmed* and are estimates; measure them in a prototype before they matter. Where a fact came from a non-first-party source (issue thread, distro packaging, vendor blog), it says so.

## Summary table

| Tool | Kind | Server? | Offline? | Licence | Pin version / rules | Output | Native seed-vs-final diff | Runtime, small repo |
|---|---|---|---|---|---|---|---|---|
| **SonarQube Community Build** + SonarScanner CLI | quality (bugs, smells, complexity, duplication, ratings), some security | **Yes**, a SonarQube server (DB + Elasticsearch) | Yes, if the server runs locally; scanner fetches analyzers from the server, not the internet | LGPL-3.0 ([repo](https://github.com/SonarSource/sonarqube)) | Docker tags `sonarqube:<ver>-community`, `sonarsource/sonar-scanner-cli:<ver>`; rules = quality profile in the server | No report file; results read back from the server web API (JSON) | Partly: "new code" period (previous version / specific analysis) inside one project; no branch/PR analysis in Community | Server start ~1–2 min + scan tens of s (*unconfirmed*) |
| **SonarQube CLI** (new, 2026) | quality + secrets | Quality analysis needs Cloud or Server 2026.5 Enterprise | **Only secrets scanning** runs offline | Not stated | — | Not checked | Change-set analysis (needs Cloud/Enterprise) | — |
| **ESLint** `complexity` (+ `max-depth`, `max-lines-per-function`) | TS quality | No | Yes, once `node_modules` installed | MIT | npm lockfile pins ESLint, plugins and config | JSON formatter built in; SARIF via `@microsoft/eslint-formatter-sarif` | No | Seconds (*unconfirmed*) |
| **golangci-lint** v2 (gocyclo, gocognit, dupl, gosec, …) | Go quality + security | No | Yes, if Go modules are in the module cache | GPL-3.0 ([repo](https://github.com/golangci/golangci-lint)) | Release binary or `golangci/golangci-lint:<ver>` image; `.golangci.yml` `version: "2"` lists linters and thresholds | text, json, tab, html, checkstyle, code-climate, junit-xml, teamcity, **sarif** | **Yes**: `issues.new-from-rev`, `new-from-patch`, `new-from-merge-base` | Seconds to tens of s (*unconfirmed*) |
| **jscpd** | duplication, TS + Go + many | No | Yes | MIT | npm version | json, **sarif**, xml, csv, html, markdown, codeclimate, … | No | Seconds (*unconfirmed*) |
| **lizard** | complexity (CCN, NLOC, tokens, params) TS + Go | No | Yes | see LICENSE.txt (not confirmed here) | pip version | tabular, CSV, XML (cppncss), checkstyle, HTML; **no JSON** | No | Seconds (*unconfirmed*) |
| **Semgrep CE** | SAST, TS + Go | No | Yes, **with local rule files** and `--metrics=off` | Engine LGPL-2.1; community rules under restrictive Semgrep Rules License v1.0 | `semgrep/semgrep:<ver>` image; vendor rule YAML at a commit | **json**, **sarif** (+ text, junit, …) | **Yes**: `--baseline-commit` (git repo, clean tree) | Tens of s (*unconfirmed*) |
| **gitleaks** | secrets | No | Yes | MIT | Release binary/image tag; rules in `.gitleaks.toml` | json, csv, junit, **sarif**, template | **Yes**: `--baseline-path` (previous report) or `git --log-opts seed..final` | Seconds (*unconfirmed*) |
| **gosec** | Go SAST | No | Yes, if Go modules are in the cache | Apache-2.0 | `go install …@vX`, image tag; `-include`/`-exclude` rule IDs | text, **json**, yaml, csv, junit-xml, html, sonarqube, golint, **sarif** | No | Seconds (*unconfirmed*) |
| **govulncheck** | Go dependency vulns, reachability | No | Yes, with `-db file://<dir>` over a downloaded `vulndb.zip` (not in the official doc; see below) | BSD-3-Clause | `go install golang.org/x/vuln/cmd/govulncheck@vX`; DB snapshot date | text, streaming **json**, **sarif**, openvex | No | Seconds (*unconfirmed*) |
| **osv-scanner** | dependency vulns (npm, Go, …) | No | Yes, `--offline` with pre-downloaded per-ecosystem DB | Apache-2.0 | Release binary/image; DB zip snapshot | table, markdown, vertical, html, **json**, **sarif**, spdx, cyclonedx | No | Seconds (*unconfirmed*) |
| **npm audit** | npm dependency vulns | Registry | **No**: posts to the registry advisory endpoint | Artistic-2.0 (npm CLI; not checked here) | — | json | No | — |

## Per tool

### SonarQube Community Build + SonarScanner

- **Server needed.** The scanner command passes `-Dsonar.host.url` and `-Dsonar.token`, and the project key must be "unique in a given SonarQube instance" ([SonarScanner CLI docs](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/scanners/sonarscanner/)). The old local "preview" mode is gone and sonarlint-cli is discontinued ([community thread](https://community.sonarsource.com/t/preview-mode-is-gone-how-to-report-issues-without-committing-them-to-database/97898); not first-party docs).
- **Offline.** The scanner downloads language analyzers *from the server* and caches them under `SONAR_USER_HOME` ([scanner docs](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/scanners/sonarscanner/)). So a server container on the same Docker network is enough; no internet is needed (*inferred, not tested*).
- **Licence.** LGPL-3.0 ([SonarSource/sonarqube README](https://github.com/SonarSource/sonarqube)). Docker image `sonarqube` (Docker Hub link from that README); scanner image `sonarsource/sonar-scanner-cli`. Scanner needs Java 21+ or JRE auto-provisioning.
- **Pinning.** Image tags pin server and scanner. Rules are the server's quality profile; to pin them, export/import the profile or keep the built-in "Sonar way" at a pinned server version (*inferred*).
- **Output.** There is no local report file. Results are read from the server web API (measures and issues). Usable per-trial fields: issue counts by type and severity, `ncloc`, `complexity`, `cognitive_complexity`, `duplicated_lines_density`, maintainability/reliability/security ratings, and the `new_*` equivalents. (Metric names are from general knowledge of the SonarQube web API, *not re-checked in this pass*.)
- **Diff.** Community Build supports all four new-code definitions: previous version, number of days, specific analysis, reference branch ([About new code](https://docs.sonarsource.com/sonarqube-community-build/user-guide/about-new-code/)). Branch analysis and PR decoration are commercial-only ([README](https://github.com/SonarSource/sonarqube)). So seed-vs-final in one project means: analyse seed with `sonar.projectVersion=seed`, then final with a new version, and read `new_*` measures. One project per trial avoids cross-talk. The "reference branch" option in a single-branch edition is unclear (*unconfirmed*).
- **Cost.** A server (Elasticsearch inside) needs memory and a start-up wait. This is the "operating a Sonar server" question already on the map.

### SonarQube CLI (2026)

- Local secrets detection "runs locally and needs no SonarQube connection" and works "offline". Code-quality analysis of local changes (`sonar analyze`) uses Vortex, which needs SonarQube Cloud Team/Enterprise or Server 2026.5 Enterprise/Data Center ([SonarQube CLI analysis docs](https://docs.sonarsource.com/sonarqube-cli/analysis/analysis)). **No serverless Sonar quality analysis exists for free.**

### ESLint (TypeScript quality)

- `complexity` rule: classic McCabe cyclomatic complexity, default `max` 20, `variant` `classic` or `modified` ([rule docs](https://eslint.org/docs/latest/rules/complexity)). It reports only functions over the threshold, so for a metric set `max` low (for example 1) and count/aggregate messages, or use lizard for raw numbers.
- Runs offline once dependencies are installed. Needs a config that can parse TS (typescript-eslint); the experiment would supply its own config rather than trust the task repo's.

### golangci-lint (Go quality and security)

- Config `version: "2"` ([config file docs](https://golangci-lint.run/docs/configuration/file/)). Linters relevant here: `gocyclo`, `gocognit` (default `min-complexity` 30, recommended 10–20), `dupl` (`threshold` 150 tokens), `gosec` ([linter config](https://golangci-lint.run/docs/linters/configuration/)).
- **Native diff:** `issues.new-from-rev: <REV>` "Show only new issues created after git revision REV"; also `new-from-patch` and `new-from-merge-base` ([config file docs](https://golangci-lint.run/docs/configuration/file/)). With the trial's git history, `new-from-rev=<seed commit>` on the final snapshot gives new issues directly.
- Output formats incl. `json` and `sarif`, each with its own `path` ([config file docs](https://golangci-lint.run/docs/configuration/file/)).
- Type-checking linters load packages, so module dependencies must be in the cache (same constraint as gosec, below). Licence GPL-3.0 ([repo](https://github.com/golangci/golangci-lint)); running it as a separate tool does not affect Assay's licence.

### jscpd (duplication)

- MIT; reporters include `json`, `sarif`, `codeclimate`, `openmetrics`, `threshold`; TS covered by the oxc parser, `--cross-formats` matches JS/TS clones; Go is listed; current major v5 ([repo README](https://github.com/kucherenko/jscpd)). The JSON statistics field names were not confirmed in the README (*check before use*).

### lizard (complexity)

- Languages include TypeScript (with TSX) and Go; metrics NLOC, CCN, token count, parameter count; `-C` CCN limit, `-a` parameter limit; claims copy-paste detection ([README](https://github.com/terryyin/lizard)). Output: default table, `--csv`, `--xml` (cppncss), `--checkstyle`, `--html`; **no JSON** ([cli.rst](https://raw.githubusercontent.com/terryyin/lizard/master/docs/cli.rst)). CSV gives per-function numbers, which suit "mean/max CCN of changed functions". Licence not confirmed here.

### Semgrep CE (SAST)

- Engine LGPL-2.1; "by default, code is never uploaded"; registry configs (`--config=p/ci`) report pseudonymous rule metrics; `--metrics=off` disables them ([repo README](https://github.com/semgrep/semgrep), [CLI reference](https://docs.semgrep.dev/cli-reference)).
- **Offline:** `--config` accepts a local YAML file or directory ([CLI reference](https://docs.semgrep.dev/cli-reference)). Registry names (`p/...`) need network, so the evaluation must ship vendored rule files. `--disable-version-check` avoids the update check.
- **Rules licence:** `semgrep/semgrep-rules` is under the Semgrep Rules License v1.0: "only for your own internal business purposes", and it "does not allow you to distribute the rules, or to make them available to others as a service" ([licence](https://semgrep.dev/legal/rules-license)). Running them in our own experiments is internal use; **bundling them into Assay's repo or image is distribution**. So a built-in `semgrep` evaluation should take the rule directory as configuration (mounted by the experimenter), or ship our own rules.
- **Native diff:** `--baseline-commit=<sha>` "Only show results that are not found in this commit hash"; it "aborts run if not currently in a git directory, there are unstaged changes, or given baseline hash doesn't exist" ([CLI reference](https://docs.semgrep.dev/cli-reference)). So it needs the trial's git history checked out clean at the final commit.
- Output: `--json`, `--sarif` (with `--json-output`/`--sarif-output` to write files) ([CLI reference](https://docs.semgrep.dev/cli-reference)). Per-result fields usable: `check_id`, `path`, `start.line`, `extra.severity` (field names from general knowledge, *not re-checked*).
- `--oss-only` forces the CE engine.

### gitleaks (secrets)

- MIT. Commands: `git` (scans `git log -p`, with `--log-opts` for ranges like `A..B`), `dir`, `stdin`. Report formats json, csv, junit, sarif, plus template. `--baseline-path` ignores findings already in a previous report. Finding fields include `RuleID`, `File`, `StartLine`, `Commit`, `Fingerprint`, `Secret`, `Entropy` ([README](https://github.com/gitleaks/gitleaks)).
- **Status warning:** the README says gitleaks is feature-complete with only security patches planned; the author is moving to Betterleaks ([README](https://github.com/gitleaks/gitleaks)).
- For trials, `gitleaks git --log-opts "<seed>..<final>"` scans only what the agent committed, which matches the per-tool-call history the trace hook records. Use `--redact` in reports so secrets are not copied into results (flag from general knowledge, *not re-checked*).

### gosec (Go SAST)

- Apache-2.0; `-fmt` text, json, yaml, csv, junit-xml, html, sonarqube, golint, sarif; `-severity` and `-confidence` filters; no baseline/diff mode documented; loads packages via Go modules, so dependencies must resolve (`go mod download`) ([README](https://github.com/securego/gosec)). Also available as a golangci-lint linter, which then gets `new-from-rev`.

### govulncheck (Go dependency vulnerabilities)

- BSD-3-Clause; `-format json` (streaming), `sarif`, `openvex`; `-mode binary`/`extract`; reports only vulnerabilities whose functions are reachable; by default queries `https://vuln.go.dev`; `-db` selects another database that implements the spec ([pkg.go.dev doc](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)).
- **Offline:** the official doc does not mention `file://`. A Go maintainer's example in [golang/go#65230](https://golang.org/issue/65230) downloads `vuln.go.dev/vulndb.zip` and runs `-db file://$PWD/vulndb`; openSUSE packages the DB for offline use the same way ([package](https://build-test-1.opensuse.org/package/show/devel:languages:go/govulncheck-vulndb?rev=6)). Secondary sources: *treat as likely, verify in a prototype*.
- Results depend on the DB snapshot, so record the DB's modified date as an input.

### osv-scanner (dependency vulnerabilities, npm and Go)

- Apache-2.0; supports Go modules and npm lockfiles ([repo](https://github.com/google/osv-scanner)). Formats: table, markdown, vertical, html, json, sarif, spdx-2-3, cyclonedx-1-5; JSON is `results[].packages[].vulnerabilities[]` and `groups[]` ([output docs](https://google.github.io/osv-scanner/output/)).
- **Offline:** `--offline` ("No network connection is required"), with per-ecosystem `all.zip` files pre-placed under `OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY` or fetched once with `--download-offline-databases` ([offline mode docs](https://google.github.io/osv-scanner/usage/offline-mode/)). It is the offline replacement for `npm audit`.

### npm audit

- Not offline: it "submits a description of the dependencies configured in your project to your default registry"; requires a lockfile by default; no offline mode documented ([npm audit docs](https://docs.npmjs.com/cli/v11/commands/npm-audit)). Exclude it, or replace it with osv-scanner.

## What a built-in evaluation would consume and produce

### Consumes

- **Two snapshots from the trial record's repository history:** the seed commit and the final commit. Most tools need a working tree; semgrep `--baseline-commit`, golangci-lint `new-from-rev` and gitleaks `--log-opts` need the **git history itself** with a clean checkout of the final commit.
- **Pinned tool image** (one container per evaluation, image tag or digest as part of the evaluation's input digest).
- **Pinned rules/config:** golangci-lint `.golangci.yml`, ESLint config, semgrep rule directory (supplied by the experimenter because of the rules licence), gitleaks config, SonarQube quality profile.
- **Pinned vulnerability DB snapshots** for govulncheck and osv-scanner (files, dated), so results do not drift between runs.
- **Dependencies for type-aware tools:** Go module cache / `node_modules` for the snapshot. These must be populated without network at evaluation time, which means either the task image already has them or the evaluation prepares them once per task pack (*open question*).
- For `sonar`: a SonarQube server container on the evaluation network, one project per trial.

### Produces (per trial)

Two shapes work for every tool:

1. **Native diff where available** (semgrep `--baseline-commit`, golangci-lint `new-from-rev`, gitleaks commit range or `--baseline-path`, Sonar `new_*` measures).
2. **Computed diff otherwise:** run on seed and on final, then match findings by `(rule id, file, fingerprint or normalised snippet)` rather than line number, since lines shift. SARIF gives a common shape (`ruleId`, `level`, `locations`, `partialFingerprints`) for most tools, so one Python matcher can cover semgrep, gosec, golangci-lint, gitleaks, govulncheck, osv-scanner, jscpd.

Suggested per-trial metrics:

- `new_findings` (count, and by severity), `fixed_findings`, `final_findings`, per tool.
- Quality: max and mean cyclomatic/cognitive complexity of functions changed by the agent; duplicated lines or % (jscpd/dupl); for `sonar`, the rating letters and `new_*` measures.
- Security: new secrets (gitleaks), new SAST findings (semgrep/gosec), vulnerable dependencies added (osv-scanner/govulncheck).
- Raw SARIF/JSON files kept as evaluation artefacts so the summary can recompute.

## Implications for the map

- A Sonar evaluation is the only option here that needs a server. Lighter tools (golangci-lint + jscpd/lizard + ESLint for quality; semgrep + gitleaks + osv-scanner/govulncheck for security) all run standalone and offline, and several already diff against a git revision.
- Semgrep's community rules cannot be shipped inside Assay; the experiment supplies them.
- Vulnerability DBs and dependency caches are new pinned inputs for evaluations.

## Unconfirmed / to check in a prototype

- Every runtime figure.
- govulncheck `-db file://` (secondary sources only).
- SonarQube web API metric names and whether one Community Build server can host many trial projects cleanly; whether "reference branch" new code is usable without branch analysis.
- jscpd JSON statistics field names; lizard licence.
- Whether golangci-lint/gosec can run with no module cache (they type-check packages).
