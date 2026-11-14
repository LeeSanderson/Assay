package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

type invcFixture struct {
	t         *testing.T
	clock     *adapters.FixedClock
	orders    *Orders
	invoicing *Invoicing
	checkout  *Checkout
}

// invcShop gives a shop with apples at 250 and pears at 1200, and 300 off
// every order of at least one pear, invoiced at the tax rate (the standard
// rate when nil). It gives the error of a broken rate.
func invcShop(t *testing.T, taxRate *int) (invcFixture, error) {
	t.Helper()
	ids := adapters.NewSequentialIDs()
	clock := adapters.NewFixedClock("2026-03-10")
	catalogue := NewCatalogue(adapters.NewInMemoryProductRepository())
	invcMust(catalogue.AddProduct("apple", "Apple", 250))(t)
	invcMust(catalogue.AddProduct("pear", "Pear", 1200))(t)
	inventory := NewInventory(adapters.NewInMemoryStockRepository())
	invcOK(t, inventory.Receive("apple", 20))
	invcOK(t, inventory.Receive("pear", 20))
	promotions := NewPromotionEngine()
	invcOK(t, promotions.AddPromotion(Promotion{ID: "off", Kind: "fixed", Amount: 300, SKUs: []string{"pear"}}))
	repository := adapters.NewInMemoryOrderRepository()
	payments := adapters.NewInMemoryPaymentGateway(ids)
	checkout := NewCheckout(CheckoutDeps{Catalogue: catalogue, Inventory: inventory, Orders: repository,
		Payments: payments, Clock: clock, IDs: ids, Promotions: promotions})
	orders := NewOrders(repository, inventory, payments)
	invoicing, err := NewInvoicing(InvoicingDeps{Invoices: adapters.NewInMemoryInvoiceRepository(), Orders: orders,
		Clock: clock, IDs: ids, TaxRate: taxRate})
	return invcFixture{t, clock, orders, invoicing, checkout}, err
}

func invcStandard(t *testing.T) invcFixture {
	t.Helper()
	return invcMust(invcShop(t, nil))(t)
}

// place places an order of the lines (each a SKU and a quantity) and gives
// its id.
func (s invcFixture) place(pairs ...any) string {
	s.t.Helper()
	cart := NewCart()
	for i := 0; i < len(pairs); i += 2 {
		invcOK(s.t, cart.Add(pairs[i].(string), pairs[i+1].(int)))
	}
	return invcMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: cart, PaymentToken: "card"}))(s.t).ID
}

func invcOrderIDs(invoices []Invoice) []string {
	ids := []string{}
	for _, invoice := range invoices {
		ids = append(ids, invoice.OrderID)
	}
	return ids
}

func invcEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := invcShow(got), invcShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func invcShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func invcErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func invcOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func invcMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestInvoicing(t *testing.T) {
	t.Run("issuing invoices", func(t *testing.T) {
		t.Run("issues the invoice of an order at the standard tax rate", func(t *testing.T) {
			s := invcStandard(t)
			id := s.place("apple", 2, "pear", 1)
			invcEq(t, invcMust(s.invoicing.Issue(id))(t), Invoice{
				ID:      "invoice-1",
				Number:  "INV-000001",
				OrderID: id,
				Lines: []InvoiceLine{
					{SKU: "apple", Description: "Apple", Quantity: 2, UnitPrice: 250, Amount: 500},
					{SKU: "pear", Description: "Pear", Quantity: 1, UnitPrice: 1200, Amount: 1200},
				},
				Subtotal:  1700,
				Discounts: []Discount{{PromotionID: "off", Amount: 300}},
				Total:     1400,
				TaxRate:   2000,
				Tax:       234,
				IssuedOn:  "2026-03-10",
			})
		})

		t.Run("uses the tax rate that it was given", func(t *testing.T) {
			rate := 500
			s := invcMust(invcShop(t, &rate))(t)
			invcEq(t, invcMust(s.invoicing.Issue(s.place("pear", 1)))(t).Tax, 43)
		})

		t.Run("rejects a broken tax rate", func(t *testing.T) {
			rate := -1
			_, err := invcShop(t, &rate)
			invcErr(t, err, "tax rate must be a whole number of basis points")
		})

		t.Run("numbers the invoices in the order of issue", func(t *testing.T) {
			s := invcStandard(t)
			first := s.place("apple", 1)
			second := s.place("apple", 2)
			invcEq(t, invcMust(s.invoicing.Issue(second))(t).Number, "INV-000001")
			invcEq(t, invcMust(s.invoicing.Issue(first))(t).Number, "INV-000002")
			invcEq(t, invcMust(s.invoicing.ByNumber("INV-000002"))(t).OrderID, first)
		})

		t.Run("issues one invoice for an order that is not cancelled", func(t *testing.T) {
			s := invcStandard(t)
			id := s.place("apple", 1)
			invcMust(s.invoicing.Issue(id))(t)
			_, err := s.invoicing.Issue(id)
			invcErr(t, err, "order "+id+" already has an invoice")
			cancelled := s.place("apple", 1)
			invcOK(t, s.orders.Cancel(cancelled))
			_, err = s.invoicing.Issue(cancelled)
			invcErr(t, err, "order "+cancelled+" is cancelled")
			_, err = s.invoicing.Issue("order-9")
			invcErr(t, err, "unknown order order-9")
		})

		t.Run("issues the invoices of every order that has none", func(t *testing.T) {
			s := invcStandard(t)
			first := s.place("apple", 1)
			invcOK(t, s.orders.Cancel(s.place("apple", 1)))
			third := s.place("apple", 1)
			invcMust(s.invoicing.Issue(third))(t)
			fourth := s.place("pear", 1)
			invcEq(t, s.invoicing.Uninvoiced(), []string{first, fourth})
			invcEq(t, invcOrderIDs(s.invoicing.IssueOutstanding()), []string{first, fourth})
			invcEq(t, s.invoicing.Uninvoiced(), []string{})
		})
	})

	t.Run("finding invoices", func(t *testing.T) {
		t.Run("finds an invoice by its id, its order or its number", func(t *testing.T) {
			s := invcStandard(t)
			id := s.place("apple", 1)
			invoice := invcMust(s.invoicing.Issue(id))(t)
			invcEq(t, invcMust(s.invoicing.Invoice(invoice.ID))(t), invoice)
			invcEq(t, invcMust(s.invoicing.InvoiceFor(id))(t), invoice)
			_, err := s.invoicing.Invoice("invoice-9")
			invcErr(t, err, "unknown invoice invoice-9")
			_, err = s.invoicing.ByNumber("INV-000009")
			invcErr(t, err, "unknown invoice INV-000009")
			_, err = s.invoicing.InvoiceFor(s.place("apple", 1))
			invcErr(t, err, "order order-2 has no invoice")
		})

		t.Run("sums up the tax of the invoices issued in a period", func(t *testing.T) {
			s := invcStandard(t)
			invcMust(s.invoicing.Issue(s.place("pear", 1)))(t) // 900, tax 150
			s.clock.Set("2026-03-20")
			invcMust(s.invoicing.Issue(s.place("apple", 6)))(t) // 1500, tax 250
			s.clock.Set("2026-04-02")
			invcMust(s.invoicing.Issue(s.place("apple", 1)))(t)
			invcEq(t, invcMust(s.invoicing.TaxSummary("2026-03-01", "2026-03-31"))(t),
				TaxSummary{From: "2026-03-01", To: "2026-03-31", Invoices: 2, Total: 2400, Tax: 400})
			invcEq(t, len(invcMust(s.invoicing.IssuedBetween("2026-04-01", "2026-04-30"))(t)), 1)
		})

		t.Run("lists the invoices whose orders were cancelled after issue", func(t *testing.T) {
			s := invcStandard(t)
			id := s.place("apple", 1)
			invcMust(s.invoicing.Issue(id))(t)
			invcMust(s.invoicing.Issue(s.place("apple", 1)))(t)
			invcOK(t, s.orders.Cancel(id))
			invcEq(t, invcOrderIDs(s.invoicing.CancelledAfterIssue()), []string{id})
		})
	})
}
