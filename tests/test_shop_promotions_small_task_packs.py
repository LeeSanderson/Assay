"""Rung C of the codebase ladder, `shop-promotions-small`, TypeScript and Go
(issue #83; PRD section 20): the promotions engine (M) of rung B, built inside
the small codebase of the order and inventory service (the catalogue, the
inventory, the carts, the orders, the payments and the checkout, with
repositories in memory) and connected to its checkout. The first rung with a
seed suite.

tests/test_task_packs.py gives both packs the checks that every pack shares,
and the checks of a purpose-written pack (the gold solution, the seed, parity,
the size ranges, the seed-suite copy and the blind solve). This module checks
that rung C asks for rung B's feature, and no more than its checkout
integration, and how the verifier treats the seed suite of a real codebase.
"""

from __future__ import annotations

import pytest

from tests.task_packs import packs, reference_case_names, verify

SLUG = "shop-promotions-small"
TS, GO = packs(SLUG)["typescript"], packs(SLUG)["go"]
RUNG_B = packs("shop-promotions-stub")
CHECKOUT_CASES = (
    "checkout",
    "prices an order with the promotions of the engine",
    "charges the payment the total after the discounts",
    "quotes a cart with the promotions of the engine",
    "quotes a cart with coupons without using them",
    "redeems the coupons of an order at checkout",
    "checks the expiry of a coupon on the date of the clock",
    "fails with the error of the engine and changes nothing",
    "uses no coupon when the payment is declined",
    "uses no coupon when the stock is short",
    "charges no payment when the total is zero",
    "refunds the total that was charged when an order is cancelled",
    "cancels an order with no payment without a refund",
    "does not give back the coupons of a cancelled order",
)
SEED_SUITE = ("cart", "catalogue", "checkout", "clock", "inventory", "orders", "payments",
              "receipt")
GOLD_FILES = ("promotions", "checkout", "orders")


def _source(pack, name: str) -> str:
    return f"{name}.ts" if pack.language == "typescript" else f"{name}.go"


def _test_file(pack, name: str) -> str:
    return f"{name}.test.ts" if pack.language == "typescript" else f"{name}_test.go"


def test_metadata_puts_the_pack_on_rung_c_the_small_codebase_and_the_feature_m():
    for pack in (TS, GO):
        meta = pack.task_toml()["metadata"]
        assert (meta["rung"], meta["seed_size"], meta["feature_size"]) == ("C", "small", "M")
        assert meta["feature_tests"] == 61


@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_seed_is_the_small_codebase_with_a_test_file_for_each_module_and_rung_bs_stub(pack):
    assert pack.production_files() == sorted(_source(pack, n) for n in (*SEED_SUITE,
                                                                         "promotions"))
    assert pack.seed_test_files() == sorted(_test_file(pack, n) for n in SEED_SUITE)
    # The engine's stub is rung B's: rung C changes the seed size only.
    assert pack.stub_text() == RUNG_B[pack.language].stub_text()


@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_feature_tests_are_rung_bs_then_the_checkout_integration(pack):
    rung_b = RUNG_B[pack.language]
    assert reference_case_names(pack) == [*reference_case_names(rung_b), *CHECKOUT_CASES]
    (text,) = pack.reference_test_texts()
    (b_text,) = rung_b.reference_test_texts()
    if pack.language == "typescript":
        # The same tests, word for word, after the imports, which add the shop.
        b_body = b_text.partition("} from './promotions.ts'\n")[2]
        assert b_body and b_body in text
    else:
        assert text.startswith(b_text)


def test_specification_is_rung_bs_with_the_checkout_added():
    for pack in (TS, GO):
        b_spec = RUNG_B[pack.language].specification()
        b_body = b_spec.partition(f"{RUNG_B[pack.language].opening}\n")[2]
        body = pack.specification().partition(f"{pack.opening}\n")[2]
        assert body.startswith(b_body.rstrip("\n"))
        assert "checkout" in body[len(b_body):]


def test_interface_rules_are_rung_bs_and_the_same_in_both_languages():
    # The pricing rules, the coupon rules and the errors are rung B's text.
    rules = [p.interface_section().partition("\n### Pricing\n")[2] for p in (TS, GO)]
    b_rules = RUNG_B["typescript"].interface_section().partition("\n### Pricing\n")[2]
    assert rules[0].strip()
    assert rules[0] == rules[1] == b_rules


def test_interface_keeps_rung_bs_engine_and_adds_the_checkout():
    for pack in (TS, GO):
        b_section = RUNG_B[pack.language].interface_section()
        engine = b_section.partition("\n### Pricing\n")[0]
        before, heading, checkout = pack.interface_section().partition("\n### Checkout\n")
        assert heading
        assert before == engine
        assert checkout.partition("\n### Pricing\n")[2]


def test_typescript_checkout_interface_names_the_entry_points_and_the_seams():
    section = TS.interface_section().partition("\n### Checkout\n")[2]
    for name in ("`checkout.ts`", "promotions?: PromotionEngine", "coupons?: string[]",
                 "quote(cart: Cart, coupons: string[] = []): Quote",
                 "placeOrder(request: CheckoutRequest): Order", "paymentId: string",
                 "`deps.promotions`", "`deps.clock`", "`''`", "`Orders.cancel(id)`"):
        assert name in section, name


def test_go_checkout_interface_names_the_entry_points_and_the_seams():
    section = GO.interface_section().partition("\n### Checkout\n")[2]
    for name in ("`checkout.go`", "Promotions *PromotionEngine", "Coupons      []string",
                 "func (c *Checkout) Quote(cart *Cart, coupons []string) (Quote, error)",
                 "func (c *Checkout) PlaceOrder(request CheckoutRequest) (Order, error)",
                 "PaymentID string", "`deps.Promotions`", "`deps.Clock`", '`""`',
                 "`(*Orders).Cancel(id)`"):
        assert name in section, name


def test_solve_sh_copies_the_engine_and_the_changed_checkout_and_orders():
    for pack in (TS, GO):
        assert sorted(pack.gold_files()) == sorted(_source(pack, n) for n in GOLD_FILES)
        solve = (pack.path / "solution" / "solve.sh").read_text(encoding="utf-8")
        for name in GOLD_FILES:
            assert _source(pack, name) in solve, name
        assert pack.gold_files()[pack.stub] == RUNG_B[pack.language].gold_files()[pack.stub]


# --- Slow: the pack images and tests/test.sh ---------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_the_engine_alone_passes_rung_bs_tests_but_not_the_checkout_integration(
        pack, pack_images, tmp_path):
    engine = {pack.stub: pack.gold_files()[pack.stub]}
    reward = verify(pack, pack_images(pack), tmp_path, engine)
    assert reward["reward"] == 0
    assert reward["reference_total"] == 61
    assert reward["reference_passed"] == 48  # each checkout case fails
    assert reward["seed_suite_passed"] == reward["seed_suite_total"] == 59


@pytest.mark.slow
@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_a_broken_checkout_fails_the_seed_suite_even_with_its_seed_test_edited(
        pack, pack_images, tmp_path):
    # The checkout places orders as shipped, not paid, and the agent edits the
    # seed test that notices to expect it. The outcome pass restores the seed
    # test, so the seed suite fails; the edited file is an agent test, whose 11
    # tests pass on their own (each Go seed test file holds its own helpers).
    gold = pack.gold_files()
    checkout, seed_test = _source(pack, "checkout"), _test_file(pack, "checkout")
    paid, shipped = (("status: 'paid',", "status: 'shipped',") if pack.language == "typescript"
                     else ('Status:    "paid",', 'Status:    "shipped",'))
    broken = gold[checkout].replace(paid, shipped)
    edited = (pack.seed / seed_test).read_text(encoding="utf-8").replace(paid, shipped)
    assert broken != gold[checkout]
    assert edited != (pack.seed / seed_test).read_text(encoding="utf-8")
    reward = verify(pack, pack_images(pack), tmp_path,
                    {**gold, checkout: broken, seed_test: edited})
    assert reward["reward"] == 0
    assert reward["seed_suite_total"] == 59
    assert reward["seed_suite_passed"] < 59
    assert reward["agent_tests_compile"] == 1
    assert reward["agent_tests_passed"] == reward["agent_tests_total"] == 11
