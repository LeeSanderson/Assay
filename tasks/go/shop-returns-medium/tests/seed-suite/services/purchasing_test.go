package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

type purFixture struct {
	clock      *adapters.FixedClock
	inventory  *Inventory
	outbox     *adapters.InMemoryOutbox
	purchasing *Purchasing
	orchard    Supplier
}

// purShop gives a shop that sells apples and pears, with one supplier,
// Orchard (supplier-1), who delivers 5 days after an order.
func purShop(t *testing.T) purFixture {
	t.Helper()
	ids := adapters.NewSequentialIDs()
	clock := adapters.NewFixedClock("2026-03-10")
	catalogue := NewCatalogue(adapters.NewInMemoryProductRepository())
	purMust(catalogue.AddProduct("apple", "Apple", 250))(t)
	purMust(catalogue.AddProduct("pear", "Pear", 1000))(t)
	inventory := NewInventory(adapters.NewInMemoryStockRepository())
	outbox := adapters.NewInMemoryOutbox()
	purchasing := NewPurchasing(PurchasingDeps{Suppliers: adapters.NewInMemorySupplierRepository(),
		Purchases: adapters.NewInMemoryPurchaseRepository(), Catalogue: catalogue, Inventory: inventory,
		Notifier: outbox, Clock: clock, IDs: ids})
	orchard := purMust(purchasing.AddSupplier("Orchard", "sales@orchard.example", 5))(t)
	return purFixture{clock, inventory, outbox, purchasing, orchard}
}

// purSent gives the shop with a purchase order of 10 apples and 2 pears
// sent to Orchard, and its id.
func purSent(t *testing.T) (purFixture, string) {
	t.Helper()
	s := purShop(t)
	draft := purMust(s.purchasing.Draft(s.orchard.ID))(t)
	purMust(s.purchasing.AddLine(draft.ID, "apple", 10, 120))(t)
	purMust(s.purchasing.AddLine(draft.ID, "pear", 2, 600))(t)
	purMust(s.purchasing.Send(draft.ID))(t)
	return s, draft.ID
}

func purLine(sku string, quantity int) []StockLine {
	return []StockLine{{SKU: sku, Quantity: quantity}}
}

func purIDs(orders []PurchaseOrder) []string {
	ids := []string{}
	for _, order := range orders {
		ids = append(ids, order.ID)
	}
	return ids
}

func purEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := purShow(got), purShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func purShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func purErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func purOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func purMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestPurchasing(t *testing.T) {
	t.Run("suppliers", func(t *testing.T) {
		t.Run("adds a supplier and finds it by id", func(t *testing.T) {
			s := purShop(t)
			purEq(t, s.orchard, Supplier{ID: "supplier-1", Name: "Orchard", Email: "sales@orchard.example", LeadTimeDays: 5})
			purEq(t, purMust(s.purchasing.Supplier("supplier-1"))(t), s.orchard)
			purEq(t, s.purchasing.Suppliers(), []Supplier{s.orchard})
			_, err := s.purchasing.Supplier("supplier-9")
			purErr(t, err, "unknown supplier supplier-9")
		})
	})

	t.Run("drafts", func(t *testing.T) {
		t.Run("drafts a purchase order and adds lines to it", func(t *testing.T) {
			s := purShop(t)
			draft := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			purMust(s.purchasing.AddLine(draft.ID, "apple", 10, 120))(t)
			purMust(s.purchasing.AddLine(draft.ID, "pear", 2, 600))(t)
			order := purMust(s.purchasing.AddLine(draft.ID, "apple", 5, 110))(t)
			purEq(t, order, PurchaseOrder{
				ID:         "purchase-1",
				SupplierID: "supplier-1",
				Lines: []PurchaseLine{
					{SKU: "apple", Quantity: 15, UnitCost: 110, Received: 0},
					{SKU: "pear", Quantity: 2, UnitCost: 600, Received: 0},
				},
				Status:    "draft",
				CreatedOn: "2026-03-10",
			})
		})

		t.Run("rejects a line of an unknown product, and a broken line", func(t *testing.T) {
			s := purShop(t)
			draft := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			_, err := s.purchasing.AddLine(draft.ID, "kiwi", 1, 100)
			purErr(t, err, "unknown product kiwi")
			_, err = s.purchasing.AddLine(draft.ID, "apple", 1, 0)
			purErr(t, err, "unit cost must be at least 1")
		})

		t.Run("removes a line from a draft", func(t *testing.T) {
			s := purShop(t)
			draft := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			purMust(s.purchasing.AddLine(draft.ID, "apple", 10, 120))(t)
			purEq(t, purMust(s.purchasing.RemoveLine(draft.ID, "apple"))(t).Lines, []PurchaseLine{})
			_, err := s.purchasing.RemoveLine(draft.ID, "apple")
			purErr(t, err, "SKU apple is not in purchase purchase-1")
		})
	})

	t.Run("sending", func(t *testing.T) {
		t.Run("sends a draft to its supplier and expects it after the lead time", func(t *testing.T) {
			s := purShop(t)
			draft := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			purMust(s.purchasing.AddLine(draft.ID, "apple", 10, 120))(t)
			purMust(s.purchasing.AddLine(draft.ID, "pear", 2, 600))(t)
			sent := purMust(s.purchasing.Send(draft.ID))(t)
			purEq(t, []any{sent.Status, sent.SentOn, sent.ExpectedOn},
				[]any{PurchaseStatus("sent"), "2026-03-10", "2026-03-15"})
			purEq(t, s.outbox.Sent(), []Message{{
				To:      "sales@orchard.example",
				Subject: "Purchase order purchase-1",
				Body:    "10 x apple at 1.20\n2 x pear at 6.00\nTotal: 24.00",
			}})
		})

		t.Run("rejects sending an empty draft, or a purchase order twice", func(t *testing.T) {
			s := purShop(t)
			draft := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			_, err := s.purchasing.Send(draft.ID)
			purErr(t, err, "purchase purchase-1 has no lines")
			purMust(s.purchasing.AddLine(draft.ID, "apple", 1, 120))(t)
			purMust(s.purchasing.Send(draft.ID))(t)
			_, err = s.purchasing.Send(draft.ID)
			purErr(t, err, "purchase purchase-1 is sent")
			_, err = s.purchasing.AddLine(draft.ID, "apple", 1, 120)
			purErr(t, err, "purchase purchase-1 is sent")
		})
	})

	t.Run("receiving", func(t *testing.T) {
		t.Run("receives a delivery into the inventory, in part", func(t *testing.T) {
			s, id := purSent(t)
			order := purMust(s.purchasing.Receive(id, purLine("apple", 4)))(t)
			purEq(t, order.Status, PurchaseStatus("sent"))
			purEq(t, []int{order.Lines[0].Received, order.Lines[1].Received}, []int{4, 0})
			purEq(t, s.inventory.Level("apple").OnHand, 4)
			purEq(t, s.purchasing.OnOrder("apple"), 6)
		})

		t.Run("is received once every unit has come in", func(t *testing.T) {
			s, id := purSent(t)
			purMust(s.purchasing.Receive(id, purLine("apple", 4)))(t)
			purEq(t, purMust(s.purchasing.ReceiveAll(id))(t).Status, PurchaseStatus("received"))
			purEq(t, []int{s.inventory.Level("apple").OnHand, s.inventory.Level("pear").OnHand}, []int{10, 2})
			purEq(t, s.purchasing.OnOrder("apple"), 0)
		})

		t.Run("rejects a delivery of more than is outstanding, and changes nothing", func(t *testing.T) {
			s, id := purSent(t)
			_, err := s.purchasing.Receive(id, []StockLine{{SKU: "apple", Quantity: 4}, {SKU: "pear", Quantity: 3}})
			purErr(t, err, "pear has 2 outstanding")
			_, err = s.purchasing.Receive(id, purLine("fig", 1))
			purErr(t, err, "SKU fig is not in purchase "+id)
			purEq(t, s.inventory.Level("apple").OnHand, 0)
		})

		t.Run("lists the purchase orders that are late", func(t *testing.T) {
			s, id := purSent(t)
			s.clock.Set("2026-03-15")
			purEq(t, s.purchasing.Late("2026-03-15"), []PurchaseOrder{})
			purEq(t, purIDs(s.purchasing.Late("2026-03-16")), []string{id})
		})
	})

	t.Run("cancelling and reordering", func(t *testing.T) {
		t.Run("cancels a purchase order until anything of it has come in", func(t *testing.T) {
			s := purShop(t)
			first := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			purEq(t, purMust(s.purchasing.Cancel(first.ID))(t).Status, PurchaseStatus("cancelled"))
			_, err := s.purchasing.Cancel(first.ID)
			purErr(t, err, "purchase purchase-1 is cancelled")
			second := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			purMust(s.purchasing.AddLine(second.ID, "apple", 2, 100))(t)
			purMust(s.purchasing.Send(second.ID))(t)
			purMust(s.purchasing.Receive(second.ID, purLine("apple", 1)))(t)
			_, err = s.purchasing.Cancel(second.ID)
			purErr(t, err, "purchase purchase-2 has been received in part")
		})

		t.Run("drafts a reorder of the SKUs that are short, counting what is on order", func(t *testing.T) {
			s := purShop(t)
			purOK(t, s.inventory.Receive("apple", 3))
			purOK(t, s.inventory.Receive("pear", 9))
			order := purMust(s.purchasing.DraftReorder(s.orchard.ID, map[string]Cents{"pear": 600, "apple": 120}, 5, 10))(t)
			if order == nil {
				t.Fatal("no draft")
			}
			purEq(t, order.Lines, []PurchaseLine{{SKU: "apple", Quantity: 7, UnitCost: 120, Received: 0}})
			purMust(s.purchasing.Send(order.ID))(t)
			again := purMust(s.purchasing.DraftReorder(s.orchard.ID, map[string]Cents{"apple": 120}, 5, 10))(t)
			purEq(t, again == nil, true)
		})

		t.Run("adds up what the shop spends with a supplier", func(t *testing.T) {
			s := purShop(t)
			first := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			purMust(s.purchasing.AddLine(first.ID, "apple", 10, 120))(t)
			second := purMust(s.purchasing.Draft(s.orchard.ID))(t)
			purMust(s.purchasing.AddLine(second.ID, "pear", 1, 600))(t)
			purMust(s.purchasing.Cancel(second.ID))(t)
			purEq(t, purMust(s.purchasing.SpendWith(s.orchard.ID))(t), 1200)
		})
	})
}
