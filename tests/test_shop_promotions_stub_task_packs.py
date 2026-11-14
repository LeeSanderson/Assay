"""Rung B of the codebase ladder, `shop-promotions-stub`, TypeScript and Go
(issue #81; PRD section 20): the promotions engine (M) of the order and
inventory domain, built from a stub. The seed suite is empty.
tests/test_task_packs.py gives both packs the checks that every pack shares,
and the checks of a purpose-written pack (the gold solution, the seed, parity
and the blind solve)."""

from __future__ import annotations

import pytest

from tests.task_packs import MODEL_SLUG, packs, verify

SLUG = "shop-promotions-stub"
TS, GO = packs(SLUG)["typescript"], packs(SLUG)["go"]

# Each error message that a feature test checks, word for word.
ERRORS = (
    "promotion <id> already exists",
    "unknown promotion kind <kind>",
    "percent must be between 1 and 100",
    "amount must be positive",
    "buy and get must be at least 1",
    "a bundle needs at least two SKUs",
    "bundle price must not be negative",
    "coupon <code> already exists",
    "usage limit must be at least 1",
    "quantity must be at least 1",
    "SKU <sku> is in more than one line",
    "unknown coupon <code>",
    "coupon <code> given more than once",
    "coupon <code> has expired",
    "coupon <code> has reached its usage limit",
)


def test_metadata_puts_the_pack_on_rung_b_a_stub_and_the_feature_m_with_no_seed_suite():
    for pack in (TS, GO):
        meta = pack.task_toml()["metadata"]
        assert (meta["rung"], meta["seed_size"], meta["feature_size"]) == ("B", "stub", "M")
        assert meta["seed_suite_tests"] == 0
        assert pack.seed_test_files() == []
        assert not pack.seed_suite.exists()


def test_verifier_is_the_model_packs_but_for_its_name():
    for pack in (TS, GO):
        script = (pack.path / "tests" / "test.sh").read_text(encoding="utf-8")
        model_script = (pack.model / "tests" / "test.sh").read_text(encoding="utf-8")
        assert SLUG in script.splitlines()[1]
        assert script.replace(SLUG, MODEL_SLUG) == model_script


def test_seed_is_the_stub_and_the_toolchain():
    assert TS.seed_files() == sorted(["promotions.ts", "package.json", "yarn.lock",
                                      ".yarnrc.yml", "tsconfig.json", "jest.config.cjs",
                                      "babel.config.cjs", "eslint.config.mjs"])
    assert GO.seed_files() == ["go.mod", "promotions.go"]


@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_specification_covers_each_part_of_the_promotions_engine(pack):
    spec = pack.specification().lower()
    for part in ("percentage", "fixed", "buy x get y", "bundle", "coupon", "expiry date",
                 "usage limit", "priority", "exclusive", "stack"):
        assert part in spec, part


def test_interface_rules_are_the_same_in_both_languages():
    # Only the types and the entry points differ: the pricing rules, the
    # coupon rules and the errors are one text.
    rules = [p.interface_section().partition("\n### Pricing\n")[2] for p in (TS, GO)]
    assert rules[0].strip()
    assert rules[0] == rules[1]


@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_interface_states_each_error_message(pack):
    section = pack.interface_section()
    for message in ERRORS:
        assert f"`{message}`" in section, message


def test_typescript_interface_names_the_entry_points():
    section = TS.interface_section()
    for name in ("`promotions.ts`", "`new PromotionEngine()`", "`addPromotion(promotion)`",
                 "`addCoupon(coupon)`", "`quote(lines, coupons, today)`",
                 "`redeem(lines, coupons, today)`", "`Error`"):
        assert name in section, name


def test_go_interface_names_the_entry_points():
    section = GO.interface_section()
    for name in ("`promotions.go`", "`package shop`", "`NewPromotionEngine()`",
                 "`AddPromotion(promotion Promotion) error`", "`AddCoupon(coupon Coupon) error`",
                 "`Quote(lines []Line, coupons []string, today string) (Quote, error)`",
                 "`Redeem(lines []Line, coupons []string, today string) (Quote, error)`"):
        assert name in section, name


def test_solve_sh_copies_the_gold_engine_over_the_stub():
    for pack in (TS, GO):
        assert list(pack.gold_files()) == [pack.stub]
        solve = (pack.path / "solution" / "solve.sh").read_text(encoding="utf-8")
        assert f"/app/{pack.stub}" in solve


# --- Slow: the pack images and tests/test.sh ---------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("pack, old, new", [
    (TS, "public quote(lines: Line[], coupons: string[], today: string): Quote {",
     "public quote(lines: Line[], today: string): Quote {"),
    (GO, "func (e *PromotionEngine) Quote(lines []Line, coupons []string, today string) ",
     "func (e *PromotionEngine) Quote(lines []Line, today string) "),
], ids=str)
def test_changed_stub_signature_fails_the_reference_compile(pack, old, new, pack_images,
                                                            tmp_path):
    gold = pack.gold_files()[pack.stub]
    changed = gold.replace(old, new)
    assert changed != gold
    reward = verify(pack, pack_images(pack), tmp_path, {pack.stub: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0
