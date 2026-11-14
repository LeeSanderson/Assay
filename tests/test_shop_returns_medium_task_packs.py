"""Rung E of the codebase ladder, `shop-returns-medium`, TypeScript and Go
(issue #87; PRD section 20): partial returns and refunds (X) in the medium
codebase. The step from rung D to rung E turns only the seed-size dial: the
specification, the Interface section and the feature tests of X are rung D's,
byte for byte, and the seed is the medium codebase (issues #85 and #86).

On rung E, the event log, the reports and the shipping are not in the
specification of X. The seed suite covers them, and the gold solution passes
the whole seed suite.

tests/test_task_packs.py gives both packs the checks that every pack shares,
and the checks of a purpose-written pack (the gold solution, the seed, parity,
the size ranges, the seed-suite copy and the blind solve).
tests/test_medium_codebase.py checks the seed itself. This module checks what
rung E adds on top of the seed.
"""

from __future__ import annotations

import pytest

from tests.task_packs import MODEL_SLUG, packs, verify

SLUG = "shop-returns-medium"
TS, GO = packs(SLUG)["typescript"], packs(SLUG)["go"]
RUNG_D = packs("shop-returns-small")


def _source(pack, name: str) -> str:
    return f"{name}.ts" if pack.language == "typescript" else f"{name}.go"


def test_metadata_puts_the_pack_on_rung_e_the_medium_codebase_and_the_feature_x():
    for pack in (TS, GO):
        meta = pack.task_toml()["metadata"]
        assert (meta["rung"], meta["seed_size"], meta["feature_size"]) == ("E", "medium", "X")
        assert meta["feature_tests"] == RUNG_D[pack.language].task_toml()["metadata"][
            "feature_tests"]


@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_specification_interface_and_feature_tests_are_rung_ds_byte_for_byte(pack):
    # PRD section 20, "The rungs": rung E turns the seed-size dial only, so X
    # has one specification, one Interface section and one set of feature
    # tests on rungs D and E.
    rung_d = RUNG_D[pack.language]
    assert (pack.path / "instruction.md").read_bytes() == (
        rung_d.path / "instruction.md").read_bytes()
    assert pack.specification() == rung_d.specification()
    assert pack.interface_section() == rung_d.interface_section()
    assert pack.reference_test_texts() == rung_d.reference_test_texts()
    assert pack.reference_count == rung_d.reference_count


def test_verifier_is_the_model_packs_but_for_its_name():
    for pack in (TS, GO):
        script = (pack.path / "tests" / "test.sh").read_text(encoding="utf-8")
        model_script = (pack.model / "tests" / "test.sh").read_text(encoding="utf-8")
        assert SLUG in script.splitlines()[1]
        assert script.replace(SLUG, MODEL_SLUG) == model_script


def test_gold_solution_adds_the_returns_service_and_its_root_entry_point():
    # The medium codebase's layers: the rules of X in the domain, the service
    # in services/, and an entry point at the root, as the other areas.
    for pack in (TS, GO):
        gold = pack.gold_files()
        for name in ("returns", "services/returns", "domain/return"):
            assert _source(pack, name) in gold, name
            assert _source(pack, name) not in pack.seed_files(), name
        for name in gold:
            assert name in pack.seed_files() or name.rsplit("/", 1)[-1].startswith(
                "return"), name


def test_both_languages_change_the_same_seed_files():
    def design(pack):
        suffix = _source(pack, "")
        return sorted(name.removesuffix(suffix).replace("-", "_") for name in pack.gold_files())
    assert design(TS) == design(GO)


def test_solve_sh_copies_each_file_of_the_gold_solution():
    for pack in (TS, GO):
        solve = (pack.path / "solution" / "solve.sh").read_text(encoding="utf-8")
        for name in pack.gold_files():
            assert name in solve, name


def test_task_toml_records_the_verifier_run_time_of_the_gold_solution():
    # Issue #87: the verifier timeout runs the gold solution with margin.
    for pack in (TS, GO):
        config = pack.task_toml()
        seconds = config["metadata"]["verifier_gold_seconds"]
        assert 0 < seconds * 2 <= config["verifier"]["timeout_sec"]


# --- Slow: the pack images and tests/test.sh ---------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_a_pricing_change_that_breaks_the_explanations_fails_only_the_seed_suite(
        pack, pack_images, tmp_path):
    # The gold solution reworks the pricing to keep each line's part of each
    # discount. Here the rework also drops the step of each promotion that
    # took nothing, which the explanations of the engine show. The returns
    # and the prices still work, so every feature test passes; the seed suite
    # catches the change.
    gold = pack.gold_files()
    promotion = _source(pack, "domain/promotion")
    old, new = ((
        "        step('nothing to take')\n", "        // the step is dropped\n")
        if pack.language == "typescript" else (
        "\t\tsteps = append(steps, step)\n",
        "\t\tif step.Outcome != \"nothing to take\" {\n\t\t\tsteps = append(steps, step)\n\t\t}\n"))
    broken = gold[promotion].replace(old, new)
    assert broken != gold[promotion]
    reward = verify(pack, pack_images(pack), tmp_path, {**gold, promotion: broken})
    assert reward["reward"] == 0
    assert reward["reference_passed"] == reward["reference_total"] == 38
    seed_suite_tests = pack.task_toml()["metadata"]["seed_suite_tests"]
    assert reward["seed_suite_total"] == seed_suite_tests
    assert reward["seed_suite_passed"] < seed_suite_tests
