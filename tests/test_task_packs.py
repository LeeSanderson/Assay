"""The checks that every committed task pack shares (PRD section 6, "Task
packs", section 15, "The TDD pack recipe", and section 20, "The checks of a
purpose-written pack"): the twelve Exercism packs of the six difficulty-ladder
rungs and the purpose-written packs of the codebase ladder, in TypeScript and
Go, listed in tests/task_packs.py. Each rung's own module
(tests/test_<rung>_task_packs.py, and for rung 1
tests/test_typescript_task_pack.py and tests/test_go_task_pack.py) checks only
what is specific to its packs.

A purpose-written pack (ADR 0006) has no Exercism source: its metadata records
the rung, the two dials, the counts and its blind solve, and its instruction
ends with the codebase footer. The two packs of a purpose-written rung must
hold the same test cases and the same seed design (check 4, parity).

The fast tests read the packs' files. The slow tests need Docker: they run
each pack's `tests/test.sh` on prepared repositories in its image with no
network, as replay does, and run each pack through Harbor with the `oracle`
and do-nothing (`nop`) agents.
"""

import json
import re
import subprocess

import pytest

from tests.task_packs import (BASE_IMAGE, CODEBASE_PACKS, CODEBASE_SLUGS, EXERCISM_PACKS,
                              FEATURE_SIZES, FIXTURE_PACKS, MODEL_SLUG, PACKS, PACKS_WITH_A_STUB,
                              REPO_ROOT, SEED_SIZE_RANGES, SEED_SIZES, SOURCE_REPO, base_image,
                              harbor_rewards, packs, reference_case_names, run_in_image,
                              seed_design, seed_suite_case_names, seed_suite_tests, stub_signatures,
                              verify)

each_pack = pytest.mark.parametrize("pack", PACKS, ids=str)
each_exercism_pack = pytest.mark.parametrize("pack", EXERCISM_PACKS, ids=str)
each_codebase_pack = pytest.mark.parametrize("pack", CODEBASE_PACKS, ids=str)
each_rung = pytest.mark.parametrize("slug", CODEBASE_SLUGS)
TS_PACKS = [p for p in PACKS if p.language == "typescript"]
GO_PACKS = [p for p in PACKS if p.language == "go"]


# --- The packs' files ---------------------------------------------------------


@each_pack
def test_seed_repository_holds_only_the_stub_and_the_toolchain_files(pack):
    toolchain = pack.lang.toolchain
    if not pack.has_stub:
        # The seed of rungs D and E has no stub: the feature adds its file.
        assert set(pack.seed_files()) >= set(toolchain)
        assert pack.feature_file not in pack.seed_files()
    elif pack.purpose_written:
        # A codebase seed holds more than a stub; the stub and the toolchain are in it.
        assert set(pack.seed_files()) >= {pack.stub, *toolchain}
    else:
        assert pack.seed_files() == sorted([pack.stub, *toolchain])
    assert sorted(pack.task_toml()["metadata"]["seed_files"]) == pack.seed_files()


@pytest.mark.parametrize("pack", PACKS + FIXTURE_PACKS, ids=str)
def test_verifier_is_the_model_packs_but_for_its_name(pack):
    # One verifier for each language: every pack, and the test-fixture packs
    # that test it (tests/test_seed_suite_verifier.py), run the model pack's
    # tests/test.sh with the slug swapped.
    script = (pack.path / "tests" / "test.sh").read_text(encoding="utf-8")
    model = (pack.model / "tests" / "test.sh").read_text(encoding="utf-8")
    assert pack.slug in script.splitlines()[1]
    assert script.replace(pack.slug, MODEL_SLUG) == model
    # The header cites the PRD as the rest of the script does.
    assert "§" not in script
    assert "PRD section 20" in script


def test_every_verifier_has_the_same_file_mode_in_git():
    scripts = [str((p.path / "tests" / "test.sh").relative_to(REPO_ROOT).as_posix())
               for p in PACKS + FIXTURE_PACKS]
    listed = subprocess.run(["git", "ls-files", "-s", "--", *scripts], cwd=REPO_ROOT,
                            capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(listed) == len(scripts)
    assert {line.split()[0] for line in listed} == {"100755"}


@each_pack
def test_seed_repository_names_no_source(pack):
    # Earlier trials recognised the exercise from these fingerprints and
    # fetched its solution.
    for path in pack.seed.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "exercism" not in text, path
            assert "please implement" not in text, path
            assert "remove this line" not in text, path


@each_pack
def test_pack_files_have_lf_line_endings(pack):
    for path in pack.path.rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


@each_pack
def test_instruction_is_the_source_instructions_then_the_interface_then_the_footer(pack):
    text = pack.instruction()
    opening = f"# Instructions\n\n{pack.opening}\n"
    assert text.startswith(opening)
    assert text.endswith(pack.footer)
    assert len(opening) < text.index("\n## Interface\n") < text.index(pack.footer)
    assert pack.interface_section().strip()


@each_pack
def test_instruction_names_no_test_command_before_the_footer(pack):
    before_footer = pack.instruction()[:pack.instruction().index(pack.footer)].lower()
    for command in ("yarn", "npm", "jest", "npx", "go test"):
        assert command not in before_footer, command
    if pack.language == "go":
        assert "test" not in before_footer


@pytest.mark.parametrize("pack", PACKS_WITH_A_STUB, ids=str)
def test_stub_keeps_the_source_signatures_with_a_not_implemented_body(pack):
    assert stub_signatures(pack) == list(pack.signatures)
    if pack.language == "typescript":
        assert "throw new Error('Not implemented')" in pack.stub_text()
    else:
        assert pack.stub_text().startswith(f"package {pack.go_package}\n")
        go_mod = (pack.seed / "go.mod").read_text(encoding="utf-8")
        assert go_mod.startswith(f"module {pack.go_package}\n")
        # A purpose-written stub returns its error, so that each feature test
        # fails on its own and none ends the run (PRD section 20, check 2).
        body = 'errors.New("not implemented")' if pack.purpose_written \
            else 'panic("not implemented")'
        assert body in pack.stub_text()


@each_pack
def test_reference_tests_carry_the_prefix(pack):
    if pack.language == "typescript":
        name = f"assay-reference.{pack.slug}.test.ts"
        assert pack.reference_tests() == [name]
        text = (pack.path / "tests" / name).read_text(encoding="utf-8")
        assert not re.search(r"\bx(it|describe)\(", text)
        assert len(re.findall(r"^\s*it\(", text, re.MULTILINE)) == pack.reference_count
    elif pack.purpose_written:
        assert pack.reference_tests() == [f"assay_reference_{pack.feature_file[:-3]}_test.go"]
    else:
        assert pack.reference_tests() == sorted([
            "assay_reference_cases_test.go", f"assay_reference_{pack.stub[:-3]}_test.go"])


@each_pack
def test_task_toml_sets_the_prd_limits(pack):
    config = pack.task_toml()
    # The codebase ladder gives each rung 3600 s (PRD section 20, "The matrix").
    assert config["agent"]["timeout_sec"] == (3600 if pack.purpose_written else 1800)
    assert config["verifier"]["timeout_sec"] == 600
    assert config["environment"]["cpus"] == 2
    assert config["environment"]["memory_mb"] == 4096
    assert config["environment"].get("network_mode", "public") == "public"


@each_pack
def test_image_is_pinned_by_digest_at_the_model_pack_toolchain(pack):
    base = base_image(pack.path)
    assert re.fullmatch(BASE_IMAGE[pack.language], base)
    assert base == base_image(pack.model)
    assert pack.task_toml()["metadata"]["base_image"] == base


@each_exercism_pack
def test_metadata_records_the_provenance_and_the_mechanical_changes(pack):
    meta = pack.task_toml()["metadata"]
    model = pack.model_task_toml()["metadata"]
    assert meta["source_repo"] == SOURCE_REPO[pack.language]
    assert re.fullmatch(r"[0-9a-f]{40}", meta["source_commit"])
    assert meta["source_commit"] == model["source_commit"]
    assert meta["red_compile_rule"] == model["red_compile_rule"]
    assert all(p.startswith(pack.exercise) for p in meta["copied_paths"])
    changes = pack.changes()
    assert "Interface section" in changes
    assert pack.stub in changes
    # No Exercism pack has a seed suite, so its verifier reports both counts as 0.
    assert "tests/test.sh: reports seed_suite_passed and seed_suite_total, both 0" in changes
    if pack.language == "typescript":
        assert set(meta["copied_paths"]) >= {
            pack.exercise + pack.stub, pack.exercise + f"{pack.slug}.test.ts",
            pack.exercise + ".meta/proof.ci.ts", pack.exercise + ".docs/instructions.md"}
        for edited in ("xit", "assay-reference.", "package.json", "tsconfig.json",
                       "babel.config.cjs", "eslint.config.mjs", "yarn.lock",
                       "@babel/preset-env", "typescript-eslint"):
            assert edited in changes, edited
    else:
        assert any(p.endswith(".meta/example.go") for p in meta["copied_paths"])
        assert any(p.endswith("cases_test.go") for p in meta["copied_paths"])
        assert "not implemented" in changes


@each_codebase_pack
def test_metadata_records_the_rung_the_dials_and_the_counts_and_no_source(pack):
    meta = pack.task_toml()["metadata"]
    for key in ("source_repo", "source_commit", "source_dir", "copied_paths", "exercise"):
        assert key not in meta, key
    assert "exercism" not in (pack.path / "task.toml").read_text(encoding="utf-8").lower()
    assert re.fullmatch(r"[B-Z]", meta["rung"])
    assert meta["seed_size"] in SEED_SIZES
    assert meta["feature_size"] in FEATURE_SIZES
    # The slow checks prove that the verifier counts this many feature tests.
    assert meta["feature_tests"] == pack.reference_count
    # The tests that the verifier counts: the leaf cases, not the describe groups.
    assert meta["seed_suite_tests"] == seed_suite_tests(pack)
    assert meta["red_compile_rule"] == pack.model_task_toml()["metadata"]["red_compile_rule"]


@each_codebase_pack
def test_metadata_records_a_blind_solve_whose_failures_each_trace_to_the_interface(pack):
    # PRD section 20, check 3: an Opus agent in control, from the prompt and
    # the seed only. Each failed hidden test names the sentence that states it.
    solve = pack.task_toml()["metadata"]["blind_solve"]
    assert solve["model"].startswith("claude-opus")
    assert solve["condition"] == "control"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", solve["date"])
    assert solve["reference_total"] == pack.reference_count
    failed = solve["failed"]
    assert solve["reference_passed"] == solve["reference_total"] - len(failed)
    cases = set(reference_case_names(pack))
    section = " ".join(pack.interface_section().split())
    for failure in failed:
        assert failure["test"] in cases, failure["test"]
        assert " ".join(failure["sentence"].split()) in section, failure["sentence"]


@each_codebase_pack
def test_seed_suite_copy_is_the_seed_test_files_in_their_seed_form(pack):
    # The verifier restores the seed suite from this copy (PRD section 20,
    # "The pack recipe"); a pack with no seed suite holds no copy.
    if not pack.seed_test_files():
        assert not pack.seed_suite.exists()
        return
    assert pack.seed_suite_copy() == pack.seed_test_files()
    for name in pack.seed_test_files():
        assert (pack.seed_suite / name).read_bytes() == (pack.seed / name).read_bytes(), name


@pytest.mark.parametrize("pack", [p for p in PACKS + FIXTURE_PACKS if p.language == "go"],
                         ids=str)
def test_go_seed_suite_copy_records_the_tests_that_the_verifier_counts(pack):
    # A Go seed suite that does not compile runs no test, so the verifier
    # reads its test count from tests/seed-suite-tests, beside the copy.
    count = pack.path / "tests" / "seed-suite-tests"
    if not pack.seed_test_files():
        assert not count.exists()
        return
    assert count.read_text(encoding="utf-8") == f"{seed_suite_tests(pack)}\n"
    assert seed_suite_tests(pack) > len(pack.seed_test_files())


@pytest.mark.parametrize("pack", FIXTURE_PACKS, ids=str)
def test_seed_suite_tests_counts_each_leaf_test_of_the_fixture_seed_suite(pack):
    # 3 tests in the top folder and 2 in a subfolder; the Go ones are
    # top-level test functions with no t.Run.
    assert seed_suite_tests(pack) == 5


@each_codebase_pack
def test_codebase_seed_is_inside_the_size_ranges_of_its_seed_size(pack):
    # PRD section 20, "The domain": lines of production code (non-blank),
    # production files, and seed-suite tests as the verifier counts them (the
    # leaf cases, not the describe groups).
    seed_size = pack.task_toml()["metadata"]["seed_size"]
    if seed_size == "stub":
        assert pack.seed_test_files() == []
        return
    ranges = SEED_SIZE_RANGES[seed_size]
    sizes = {"lines": pack.production_lines(), "files": len(pack.production_files()),
             "tests": seed_suite_tests(pack)}
    for key, (least, most) in ranges.items():
        assert least <= sizes[key] <= most, (key, sizes[key])


@each_codebase_pack
def test_pack_adds_no_package_or_import_to_the_toolchain(pack):
    if pack.language == "typescript":
        package = json.loads((pack.seed / "package.json").read_text(encoding="utf-8"))
        model = json.loads((pack.model / "environment" / "seed" / "package.json")
                           .read_text(encoding="utf-8"))
        assert {**package, "name": ""} == {**model, "name": ""}
        lock = (pack.seed / "yarn.lock").read_text(encoding="utf-8")
        model_lock = (pack.model / "environment" / "seed" / "yarn.lock").read_text(
            encoding="utf-8")
        assert sorted(lock.replace(pack.slug, "split-second-stopwatch").splitlines()) \
            == sorted(model_lock.splitlines())
        for path in pack.path.rglob("*.ts"):
            for source in re.findall(r"from '([^']+)'", path.read_text(encoding="utf-8")):
                assert source.startswith(".") or source == "@jest/globals", (path, source)
    else:
        go_mod = (pack.seed / "go.mod").read_text(encoding="utf-8")
        assert "require" not in go_mod
        for path in pack.path.rglob("*.go"):
            text = path.read_text(encoding="utf-8")
            imports = re.findall(r'^\s*(?:import\s+)?(?:\w+\s+)?"([^"]+)"$', text, re.MULTILINE)
            for name in imports:
                first = name.split("/")[0]
                assert "." not in first or name.startswith(pack.go_package + "/"), (path, name)


@each_rung
def test_the_two_languages_of_a_rung_hold_the_same_test_cases_and_seed_design(slug):
    ts, go = packs(slug)["typescript"], packs(slug)["go"]
    assert reference_case_names(ts) == reference_case_names(go)
    # Unique names, so that a failed test traces to one case in each language.
    assert len(set(reference_case_names(ts))) == len(reference_case_names(ts))
    assert seed_suite_case_names(ts) == seed_suite_case_names(go)
    assert seed_design(ts) == seed_design(go)
    assert ts.specification() == go.specification()
    ts_meta, go_meta = ts.task_toml()["metadata"], go.task_toml()["metadata"]
    for key in ("rung", "seed_size", "feature_size", "feature_tests", "seed_suite_tests"):
        assert ts_meta[key] == go_meta[key], key


@pytest.mark.parametrize("pack", TS_PACKS, ids=str)
def test_typescript_toolchain_files_are_the_model_packs(pack):
    for name in (".yarnrc.yml", "tsconfig.json", "jest.config.cjs", "babel.config.cjs",
                 "eslint.config.mjs"):
        assert (pack.seed / name).read_bytes() == (pack.model / "environment" / "seed"
                                                   / name).read_bytes(), name
    package = json.loads((pack.seed / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == pack.slug


# --- Slow: the pack images and tests/test.sh ----------------------------------


def _seed_suite_tests(pack) -> int:
    return pack.task_toml()["metadata"]["seed_suite_tests"] if pack.purpose_written else 0


@pytest.mark.slow
@each_pack
def test_image_holds_only_the_seed_commit_and_no_claude_config(pack, pack_images):
    result = run_in_image(pack, pack_images(pack), " ; ".join([
        "cd /app", "git log --format=%s", "git ls-files", "git status --porcelain | wc -l",
        "test -e ~/.claude/skills && echo HAS_SKILLS", "test -e /app/.claude && echo HAS_CLAUDE",
        "true"]))
    assert result.returncode == 0, result.stderr
    lines = result.stdout.split()
    assert lines[0] == "seed"
    assert sorted(lines[1:-1]) == pack.seed_files()
    assert lines[-1] == "0"


@pytest.mark.slow
@each_pack
def test_gold_solution_gives_reward_1(pack, pack_images, tmp_path):
    reward = verify(pack, pack_images(pack), tmp_path, pack.gold_files())
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == pack.reference_count
    assert reward["agent_tests_total"] == 0
    assert reward["seed_suite_passed"] == reward["seed_suite_total"] == _seed_suite_tests(pack)


@pytest.mark.slow
@each_pack
def test_untouched_seed_gives_reward_0_and_passes_no_feature_test(pack, pack_images, tmp_path):
    reward = verify(pack, pack_images(pack), tmp_path)
    assert reward["reward"] == 0
    assert reward["agent_tests_total"] == 0
    if not pack.has_stub:
        # A seed with no stub lacks the feature's entry points, so no feature
        # test compiles, and none passes. In Go the feature tests compile in the
        # root package with the seed tests there, so the outcome pass does not
        # compile and the seed suite passes none of its tests, each of which
        # counts. The next test runs the seed suite on its own.
        assert reward["reference_compiles"] == 0
        assert reward["reference_passed"] == 0
        if pack.language == "go":
            assert reward["seed_suite_passed"] == 0
            assert reward["seed_suite_total"] == _seed_suite_tests(pack)
        else:
            assert reward["seed_suite_passed"] == reward["seed_suite_total"] \
                == _seed_suite_tests(pack)
        return
    assert reward["seed_suite_passed"] == reward["seed_suite_total"] == _seed_suite_tests(pack)
    assert reward["reference_compiles"] == 1
    if pack.purpose_written:
        # PRD section 20, check 2: the seed fails each feature test, and each one runs.
        assert reward["reference_passed"] == 0
        assert reward["reference_total"] == pack.reference_count


@pytest.mark.slow
@pytest.mark.parametrize("pack", [p for p in CODEBASE_PACKS if p.seed_test_files()], ids=str)
def test_seed_suite_passes_on_the_unchanged_seed(pack, pack_images):
    # The seed suite on its own, in the seed repository, with no feature test.
    command = ("corepack yarn jest --ci" if pack.language == "typescript"
               else "go test -count=1 ./...")
    result = run_in_image(pack, pack_images(pack), f"cd /app && {command}")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.slow
@each_pack
def test_agent_test_that_does_not_compile_leaves_the_outcome_pass_unaffected(pack, pack_images,
                                                                             tmp_path):
    name, content = pack.agent_test_not_compiling()
    reward = verify(pack, pack_images(pack), tmp_path, {**pack.gold_files(), name: content})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == pack.reference_count
    # The red-compile rule: no agent test passes, and each agent test file counts.
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1


# --- Slow: Harbor ---------------------------------------------------------------


@pytest.mark.slow
@each_pack
def test_harbor_oracle_agent_gets_reward_1(pack, tmp_path):
    rewards = harbor_rewards(pack, "oracle", tmp_path)
    assert rewards["reward"] == 1
    assert rewards["reference_passed"] == rewards["reference_total"] == pack.reference_count


@pytest.mark.slow
@each_pack
def test_harbor_do_nothing_agent_gets_reward_0(pack, tmp_path):
    rewards = harbor_rewards(pack, "nop", tmp_path)
    assert rewards["reward"] == 0
    assert rewards["reference_compiles"] == int(pack.has_stub)
    assert rewards["agent_tests_total"] == 0
