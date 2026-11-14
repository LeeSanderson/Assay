"""Rung D of the codebase ladder, `shop-returns-small`, TypeScript and Go
(issue #84; PRD section 20): partial returns and refunds (X), a cross-cutting
feature, in the small codebase of the order and inventory service with the
gold solution of the promotions engine (M). X changes the order lines, the
restock rules of the inventory, the prices (a return reverses each discount in
proportion) and the payments (credit notes).

tests/test_task_packs.py gives both packs the checks that every pack shares,
and the checks of a purpose-written pack (the gold solution, the seed, parity,
the size ranges, the seed-suite copy and the blind solve). This module checks
that rung D turns only the feature dial from rung C: its seed is rung C's seed
with rung C's gold solution added, and nothing else. Rung E reuses the
specification, the Interface section and the feature tests of X unchanged.
"""

from __future__ import annotations

import re

import pytest

from tests.task_packs import packs, reference_case_names, verify

SLUG = "shop-returns-small"
TS, GO = packs(SLUG)["typescript"], packs(SLUG)["go"]
RUNG_C = packs("shop-promotions-small")
GOLD_FILES = ("returns", "promotions", "checkout", "orders", "inventory", "payments")
# The messages of the errors of X, as the Interface section states them.
ERRORS = (
    "unknown order <id>",
    "order <id> is <status>",
    "the return window of order <id> has closed",
    "nothing to return",
    "SKU <sku> is not in order <id>",
    "SKU <sku> is in more than one line",
    "quantity must be at least 1",
    "unknown condition <condition>",
    "<sku> has <n> left to return",
)
GROUPS = ("returns", "restock", "refunds with discounts", "payments", "orders",
          "the return window", "errors")


def _source(pack, name: str) -> str:
    return f"{name}.ts" if pack.language == "typescript" else f"{name}.go"


def test_metadata_puts_the_pack_on_rung_d_the_small_codebase_and_the_feature_x():
    for pack in (TS, GO):
        meta = pack.task_toml()["metadata"]
        assert (meta["rung"], meta["seed_size"], meta["feature_size"]) == ("D", "small", "X")
        assert meta["feature_tests"] == 38
        assert meta["seed_suite_tests"] == RUNG_C[pack.language].task_toml()["metadata"][
            "seed_suite_tests"]


@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_seed_is_rung_cs_seed_with_rung_cs_gold_solution_and_nothing_else(pack):
    # PRD section 20, "The rungs": rung D turns the feature dial only. The one
    # other change is the package name, which is each pack's slug.
    rung_c = RUNG_C[pack.language]
    gold = rung_c.gold_files()
    assert pack.seed_files() == sorted(set(rung_c.seed_files()) | set(gold))
    for name in pack.seed_files():
        want = gold[name] if name in gold else (rung_c.seed / name).read_text(encoding="utf-8")
        got = (pack.seed / name).read_text(encoding="utf-8")
        assert got.replace(SLUG, rung_c.slug) == want, name
    assert (pack.path / "environment" / "Dockerfile").read_bytes() == (
        rung_c.path / "environment" / "Dockerfile").read_bytes()


def test_seed_has_no_stub_of_the_feature_and_the_engine_is_rung_cs_gold():
    for pack in (TS, GO):
        assert _source(pack, "returns") not in pack.seed_files()
        assert (pack.seed / _source(pack, "promotions")).read_text(encoding="utf-8") == \
            RUNG_C[pack.language].gold_files()[_source(pack, "promotions")]


def test_feature_tests_group_their_cases_by_the_parts_of_the_shop_that_x_changes():
    for pack in (TS, GO):
        names = reference_case_names(pack)
        groups = [name for name in names if name in GROUPS]
        assert groups == list(GROUPS)


def test_interface_states_each_error_and_the_feature_tests_check_each_one():
    for pack in (TS, GO):
        errors = pack.interface_section().partition("\n### Errors\n")[2]
        (text,) = pack.reference_test_texts()
        for message in ERRORS:
            assert f"`{message}`" in errors, message
            # The message with each placeholder as a value: a fixed text, or the
            # id of an order that the test placed.
            pattern = re.escape(message)
            for placeholder in ("<id>", "<status>", "<sku>", "<n>", "<condition>"):
                pattern = pattern.replace(re.escape(placeholder), r"[^'\"`]+")
            assert re.search(pattern, text), message


def test_interface_rules_are_the_same_in_both_languages_but_for_the_names():
    # Rung E reuses the rules; each section after the types names the same rules.
    headings = [re.findall(r"^### .*$", p.interface_section(), re.MULTILINE) for p in (TS, GO)]
    assert headings[0] == headings[1] == ["### Returns", "### Restock", "### Refunds",
                                          "### Payments", "### Orders", "### Errors"]


def test_typescript_interface_names_the_entry_points_and_the_parts_of_the_shop():
    section = TS.interface_section()
    for name in ("`returns.ts`", "export class Returns {", "constructor(deps: ReturnsDeps)",
                 "returnItems(orderId: string, lines: ReturnLine[]): CreditNote",
                 "creditNotes(orderId: string): CreditNote[]",
                 "export type ItemCondition = 'resellable' | 'damaged'",
                 "promotions?: PromotionEngine", "refunds(): Refund[]", "`deps.clock`",
                 "`deps.ids`", "`'credit'`", "reason: 'returned'", "floor(part * r / q)"):
        assert name in section, name


def test_go_interface_names_the_entry_points_and_the_parts_of_the_shop():
    section = GO.interface_section()
    for name in ("`returns.go`", "func NewReturns(deps ReturnsDeps) *Returns",
                 "func (r *Returns) ReturnItems(orderID string, lines []ReturnLine) "
                 "(CreditNote, error)",
                 "func (r *Returns) CreditNotes(orderID string) ([]CreditNote, error)",
                 'type ItemCondition string // "resellable" or "damaged"',
                 "Promotions *PromotionEngine", "func (g *InMemoryPaymentGateway) Refunds() []Refund",
                 "`deps.Clock`", "`deps.IDs`", '`"credit"`', 'Reason: "returned"',
                 "floor(part * r / q)"):
        assert name in section, name


def test_solve_sh_copies_the_returns_and_the_changed_modules():
    for pack in (TS, GO):
        assert sorted(pack.gold_files()) == sorted(_source(pack, n) for n in GOLD_FILES)
        solve = (pack.path / "solution" / "solve.sh").read_text(encoding="utf-8")
        for name in GOLD_FILES:
            assert _source(pack, name) in solve, name


# --- Slow: the pack images and tests/test.sh ---------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_an_order_that_always_lists_its_credit_notes_fails_the_seed_suite(
        pack, pack_images, tmp_path):
    # The returns work, but every order now carries an empty list of credit
    # notes, which a seed test that compares a whole saved order notices.
    gold = pack.gold_files()
    orders = _source(pack, "orders")
    old, new = ((
        "  if (order.creditNotes !== undefined) {",
        "  copied.creditNotes = []\n  if (order.creditNotes !== undefined) {")
        if pack.language == "typescript" else (
        "func copyOrder(order Order) Order {",
        "func copyOrder(order Order) Order {\n\tif order.CreditNotes == nil {\n"
        "\t\torder.CreditNotes = []CreditNote{}\n\t}"))
    broken = gold[orders].replace(old, new)
    assert broken != gold[orders]
    reward = verify(pack, pack_images(pack), tmp_path, {**gold, orders: broken})
    assert reward["reward"] == 0
    assert reward["reference_passed"] == reward["reference_total"] == 38
    assert reward["seed_suite_total"] == 59
    assert reward["seed_suite_passed"] < 59
