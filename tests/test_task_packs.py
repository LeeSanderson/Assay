"""The checks that every committed task pack shares (PRD section 6, "Task
packs", and section 15, "The TDD pack recipe"): the twelve packs of the six
ladder rungs, in TypeScript and Go, listed in tests/task_packs.py. Each rung's
own module (tests/test_<rung>_task_packs.py, and for rung 1
tests/test_typescript_task_pack.py and tests/test_go_task_pack.py) checks
only what is specific to its packs.

The fast tests read the packs' files. The slow tests need Docker: they run
each pack's `tests/test.sh` on prepared repositories in its image with no
network, as replay does, and run each pack through Harbor with the `oracle`
and do-nothing (`nop`) agents.
"""

import json
import re

import pytest

from tests.task_packs import (BASE_IMAGE, PACKS, SOURCE_REPO, TS_TOOLCHAIN, base_image,
                              harbor_rewards, run_in_image, stub_signatures, verify)

each_pack = pytest.mark.parametrize("pack", PACKS, ids=str)
TS_PACKS = [p for p in PACKS if p.language == "typescript"]
GO_PACKS = [p for p in PACKS if p.language == "go"]


# --- The packs' files ---------------------------------------------------------


@each_pack
def test_seed_repository_holds_only_the_stub_and_the_toolchain_files(pack):
    toolchain = TS_TOOLCHAIN if pack.language == "typescript" else ("go.mod",)
    assert pack.seed_files() == sorted([pack.stub, *toolchain])
    assert sorted(pack.task_toml()["metadata"]["seed_files"]) == pack.seed_files()


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


@each_pack
def test_stub_keeps_the_source_signatures_with_a_not_implemented_body(pack):
    assert stub_signatures(pack) == list(pack.signatures)
    if pack.language == "typescript":
        assert "throw new Error('Not implemented')" in pack.stub_text()
    else:
        assert pack.stub_text().startswith(f"package {pack.go_package}\n")
        go_mod = (pack.seed / "go.mod").read_text(encoding="utf-8")
        assert go_mod.startswith(f"module {pack.go_package}\n")
        assert 'panic("not implemented")' in pack.stub_text()


@each_pack
def test_reference_tests_carry_the_prefix(pack):
    if pack.language == "typescript":
        name = f"assay-reference.{pack.slug}.test.ts"
        assert pack.reference_tests() == [name]
        text = (pack.path / "tests" / name).read_text(encoding="utf-8")
        assert not re.search(r"\bx(it|describe)\(", text)
        assert len(re.findall(r"^\s*it\(", text, re.MULTILINE)) == pack.reference_count
    else:
        assert pack.reference_tests() == sorted([
            "assay_reference_cases_test.go", f"assay_reference_{pack.stub[:-3]}_test.go"])


@each_pack
def test_task_toml_sets_the_prd_limits(pack):
    config = pack.task_toml()
    assert config["agent"]["timeout_sec"] == 1800
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


@each_pack
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


@pytest.mark.parametrize("pack", TS_PACKS, ids=str)
def test_typescript_toolchain_files_are_the_model_packs(pack):
    for name in (".yarnrc.yml", "tsconfig.json", "jest.config.cjs", "babel.config.cjs",
                 "eslint.config.mjs"):
        assert (pack.seed / name).read_bytes() == (pack.model / "environment" / "seed"
                                                   / name).read_bytes(), name
    package = json.loads((pack.seed / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == pack.slug


# --- Slow: the pack images and tests/test.sh ----------------------------------


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
    reward = verify(pack, pack_images(pack), tmp_path, {pack.stub: pack.gold()})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == pack.reference_count
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
@each_pack
def test_untouched_stub_gives_reward_0_and_the_reference_tests_compile(pack, pack_images,
                                                                       tmp_path):
    reward = verify(pack, pack_images(pack), tmp_path)
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
@each_pack
def test_agent_test_that_does_not_compile_leaves_the_outcome_pass_unaffected(pack, pack_images,
                                                                             tmp_path):
    name, content = pack.agent_test_not_compiling()
    reward = verify(pack, pack_images(pack), tmp_path, {pack.stub: pack.gold(), name: content})
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
    assert rewards["reference_compiles"] == 1
    assert rewards["agent_tests_total"] == 0
