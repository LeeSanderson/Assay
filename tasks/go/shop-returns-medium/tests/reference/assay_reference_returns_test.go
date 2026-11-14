package shop

import (
	"fmt"
	"reflect"
	"testing"
)

const retPlacedOn = "2026-03-10"

type retFixture struct {
	clock     *FixedClock
	engine    *PromotionEngine
	inventory *Inventory
	payments  *InMemoryPaymentGateway
	checkout  *Checkout
	orders    *Orders
	returns   *Returns
	t         *testing.T
}

// retShop gives a shop with apples at 250 and pears at 1000, 20 of each in
// stock, and the promotions in its engine. The clock is on the date the
// orders are placed.
func retShop(t *testing.T, promotions ...Promotion) retFixture {
	t.Helper()
	ids := NewSequentialIDs()
	clock := NewFixedClock(retPlacedOn)
	catalogue := NewCatalogue(NewInMemoryProductRepository())
	_, err := catalogue.AddProduct("apple", "Apple", 250)
	retMust(t, err)
	_, err = catalogue.AddProduct("pear", "Pear", 1000)
	retMust(t, err)
	inventory := NewInventory(NewInMemoryStockRepository())
	retMust(t, inventory.Receive("apple", 20))
	retMust(t, inventory.Receive("pear", 20))
	engine := NewPromotionEngine()
	for _, promotion := range promotions {
		retMust(t, engine.AddPromotion(promotion))
	}
	repository := NewInMemoryOrderRepository()
	payments := NewInMemoryPaymentGateway(ids)
	checkout := NewCheckout(CheckoutDeps{
		Catalogue:  catalogue,
		Inventory:  inventory,
		Orders:     repository,
		Payments:   payments,
		Clock:      clock,
		IDs:        ids,
		Promotions: engine,
	})
	orders := NewOrders(repository, inventory, payments)
	returns := NewReturns(ReturnsDeps{
		Orders:    repository,
		Inventory: inventory,
		Payments:  payments,
		Clock:     clock,
		IDs:       ids,
	})
	return retFixture{clock, engine, inventory, payments, checkout, orders, returns, t}
}

// place places an order of the lines, each a SKU and a quantity.
func (s retFixture) place(lines ...CartLine) Order {
	s.t.Helper()
	cart := NewCart()
	for _, line := range lines {
		retMust(s.t, cart.Add(line.SKU, line.Quantity))
	}
	order, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: cart, PaymentToken: "card"})
	retMust(s.t, err)
	return order
}

// shipped places an order of the lines and ships it.
func (s retFixture) shipped(lines ...CartLine) Order {
	s.t.Helper()
	order := s.place(lines...)
	retMust(s.t, s.orders.Ship(order.ID))
	return order
}

// give returns the lines from the order, and fails the test on an error.
func (s retFixture) give(orderID string, lines ...ReturnLine) CreditNote {
	s.t.Helper()
	note, err := s.returns.ReturnItems(orderID, lines)
	retMust(s.t, err)
	return note
}

func retResellable(sku string, quantity int) ReturnLine {
	return ReturnLine{SKU: sku, Quantity: quantity, Condition: "resellable"}
}

func retDamaged(sku string, quantity int) ReturnLine {
	return ReturnLine{SKU: sku, Quantity: quantity, Condition: "damaged"}
}

func retLine(sku string, quantity int) CartLine {
	return CartLine{SKU: sku, Quantity: quantity}
}

func retMust(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// retWant fails the test unless got and want are deeply equal; an empty and
// a nil slice are the same.
func retWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(retPlain(got), retPlain(want)) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

// retPlain gives the value with each empty slice as nil.
func retPlain(value any) any {
	return retPlainValue(reflect.ValueOf(value)).Interface()
}

func retPlainValue(v reflect.Value) reflect.Value {
	switch v.Kind() {
	case reflect.Slice:
		if v.Len() == 0 {
			return reflect.Zero(v.Type())
		}
		out := reflect.MakeSlice(v.Type(), v.Len(), v.Len())
		for i := 0; i < v.Len(); i++ {
			out.Index(i).Set(retPlainValue(v.Index(i)))
		}
		return out
	case reflect.Struct:
		out := reflect.New(v.Type()).Elem()
		for i := 0; i < v.NumField(); i++ {
			if out.Field(i).CanSet() {
				out.Field(i).Set(retPlainValue(v.Field(i)))
			}
		}
		return out
	}
	return v
}

// retWantError fails the test unless err is an error with the text want.
func retWantError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

// retWithoutID gives the credit note without its id, which the tests do not
// fix.
func retWithoutID(t *testing.T, note CreditNote) CreditNote {
	t.Helper()
	if note.ID == "" {
		t.Fatalf("the credit note has no id")
	}
	note.ID = ""
	return note
}

func retDiscounts(pairs ...any) []Discount {
	var list []Discount
	for i := 0; i < len(pairs); i += 2 {
		list = append(list, Discount{PromotionID: pairs[i].(string), Amount: pairs[i+1].(int)})
	}
	return list
}

func retCreditNotes(t *testing.T, returns *Returns, orderID string) []CreditNote {
	t.Helper()
	notes, err := returns.CreditNotes(orderID)
	retMust(t, err)
	return notes
}

func retStatus(t *testing.T, orders *Orders, orderID string) OrderStatus {
	t.Helper()
	order, err := orders.Order(orderID)
	retMust(t, err)
	return order.Status
}

func retRefunded(payments *InMemoryPaymentGateway) int {
	total := 0
	for _, refund := range payments.Refunds() {
		total += refund.Amount
	}
	return total
}

var retTenPercent = Promotion{ID: "ten", Kind: "percentage", Percent: 10}

func TestReturns(t *testing.T) {
	t.Run("returns", func(t *testing.T) {
		t.Run("returns part of a shipped order and issues a credit note", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 4))
			note := s.give(order.ID, retResellable("apple", 1))
			retWant(t, retWithoutID(t, note), CreditNote{
				OrderID:  order.ID,
				Lines:    []CreditLine{{SKU: "apple", Quantity: 1, Amount: 250}},
				Amount:   250,
				IssuedOn: retPlacedOn,
			})
		})

		t.Run("returns several lines in one credit note, in the order of the return", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 4), retLine("pear", 2))
			note := s.give(order.ID, retResellable("pear", 1), retResellable("apple", 2))
			retWant(t, note.Lines, []CreditLine{
				{SKU: "pear", Quantity: 1, Amount: 1000},
				{SKU: "apple", Quantity: 2, Amount: 500},
			})
			retWant(t, note.Amount, 1500)
		})

		t.Run("issues the credit note on the date of the clock", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 4))
			s.clock.Set("2026-03-25")
			retWant(t, s.give(order.ID, retResellable("apple", 1)).IssuedOn, "2026-03-25")
		})

		t.Run("gives each credit note its own id and lists the credit notes of an order", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 4))
			first := s.give(order.ID, retResellable("apple", 1))
			second := s.give(order.ID, retResellable("apple", 2))
			if first.ID == second.ID {
				t.Fatalf("both credit notes have the id %q", first.ID)
			}
			retWant(t, retCreditNotes(t, s.returns, order.ID), []CreditNote{first, second})
		})

		t.Run("lists no credit notes for an order with no return", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 1))
			retWant(t, retCreditNotes(t, s.returns, order.ID), []CreditNote{})
		})

		t.Run("keeps the lines and the totals of the order as placed", func(t *testing.T) {
			s := retShop(t, retTenPercent)
			order := s.shipped(retLine("apple", 4), retLine("pear", 1))
			s.give(order.ID, retResellable("apple", 1))
			after, err := s.orders.Order(order.ID)
			retMust(t, err)
			var lines []string
			for _, line := range after.Lines {
				lines = append(lines, fmt.Sprintf("%s %d %d", line.SKU, line.UnitPrice, line.Quantity))
			}
			retWant(t, lines, []string{"apple 250 4", "pear 1000 1"})
			retWant(t, []int{after.Subtotal, after.Total}, []int{2000, 1800})
			retWant(t, after.Discounts, retDiscounts("ten", 200))
		})
	})

	t.Run("restock", func(t *testing.T) {
		t.Run("puts resellable units back into the stock on hand", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 4))
			s.give(order.ID, retResellable("apple", 3))
			retWant(t, s.inventory.Level("apple"), StockLevel{SKU: "apple", OnHand: 19, Reserved: 0})
			movements := s.inventory.Movements("apple")
			retWant(t, movements[len(movements)-1], StockMovement{SKU: "apple", Quantity: 3, Reason: "returned"})
		})

		t.Run("does not put damaged units back into stock", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 4))
			before := s.inventory.Movements("apple")
			note := s.give(order.ID, retDamaged("apple", 3))
			retWant(t, note.Amount, 750)
			retWant(t, s.inventory.Level("apple"), StockLevel{SKU: "apple", OnHand: 16, Reserved: 0})
			retWant(t, s.inventory.Movements("apple"), before)
		})

		t.Run("restocks each line of a return by its condition", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 4), retLine("pear", 2))
			s.give(order.ID, retDamaged("apple", 1), retResellable("pear", 2))
			retWant(t, s.inventory.Available("apple"), 16)
			retWant(t, s.inventory.Available("pear"), 20)
		})
	})

	t.Run("refunds with discounts", func(t *testing.T) {
		t.Run("reverses a percentage discount in proportion to the units returned", func(t *testing.T) {
			s := retShop(t, retTenPercent)
			order := s.shipped(retLine("apple", 4))
			note := s.give(order.ID, retResellable("apple", 1))
			retWant(t, note.Lines, []CreditLine{{SKU: "apple", Quantity: 1, Amount: 225}})
			retWant(t, note.Discounts, retDiscounts("ten", 25))
			retWant(t, note.Amount, 225)
		})

		t.Run("rounds each reversal down and reverses the whole discount once every unit is back", func(t *testing.T) {
			s := retShop(t, Promotion{ID: "fifteen", Kind: "percentage", Percent: 15})
			order := s.shipped(retLine("apple", 3)) // 750, less a discount of 112
			var amounts []int
			for range 3 {
				amounts = append(amounts, s.give(order.ID, retResellable("apple", 1)).Amount)
			}
			retWant(t, amounts, []int{213, 213, 212})
			var discounts [][]Discount
			for _, note := range retCreditNotes(t, s.returns, order.ID) {
				discounts = append(discounts, note.Discounts)
			}
			retWant(t, discounts, [][]Discount{
				retDiscounts("fifteen", 37), retDiscounts("fifteen", 37), retDiscounts("fifteen", 38),
			})
		})

		t.Run("reverses only the discounts that took from the returned line", func(t *testing.T) {
			s := retShop(t, Promotion{ID: "apples", Kind: "percentage", Percent: 10, SKUs: []string{"apple"}})
			order := s.shipped(retLine("apple", 2), retLine("pear", 1))
			note := s.give(order.ID, retResellable("pear", 1))
			retWant(t, note.Amount, 1000)
			retWant(t, note.Discounts, []Discount{})
		})

		t.Run("reverses a fixed discount on the lines that it took from", func(t *testing.T) {
			// 300 off: 250 from the apple line, then 50 from the pear line.
			s := retShop(t, Promotion{ID: "off", Kind: "fixed", Amount: 300})
			order := s.shipped(retLine("apple", 1), retLine("pear", 1))
			note := s.give(order.ID, retResellable("pear", 1))
			retWant(t, note.Lines, []CreditLine{{SKU: "pear", Quantity: 1, Amount: 950}})
			retWant(t, note.Discounts, retDiscounts("off", 50))
		})

		t.Run("reverses a buy-x-get-y discount in proportion to the units returned", func(t *testing.T) {
			s := retShop(t, Promotion{ID: "three-for-two", Kind: "buy-x-get-y", Buy: 2, Get: 1})
			order := s.shipped(retLine("apple", 3)) // 750, less one free apple
			note := s.give(order.ID, retResellable("apple", 1))
			retWant(t, note.Amount, 167)
			retWant(t, note.Discounts, retDiscounts("three-for-two", 83))
		})

		t.Run("gives a bundle that is returned in part a new price", func(t *testing.T) {
			// Two sets of an apple and a pear at 900: a saving of 700, 500 from the
			// apple line and 200 from the pear line.
			s := retShop(t, Promotion{ID: "pair", Kind: "bundle", SKUs: []string{"apple", "pear"}, Price: 900})
			order := s.shipped(retLine("apple", 2), retLine("pear", 2))
			retWant(t, order.Total, 1800)
			note := s.give(order.ID, retResellable("pear", 1))
			retWant(t, note.Lines, []CreditLine{{SKU: "pear", Quantity: 1, Amount: 900}})
			retWant(t, note.Discounts, retDiscounts("pair", 100))
			retWant(t, s.orders.Revenue(), 900)
		})

		t.Run("reverses each discount on a line on its own, in the order of the discounts", func(t *testing.T) {
			s := retShop(t,
				Promotion{ID: "ten", Kind: "percentage", Percent: 10, Priority: 1},
				Promotion{ID: "off", Kind: "fixed", Amount: 100})
			order := s.shipped(retLine("apple", 4)) // 1000, less 100 and then 100
			note := s.give(order.ID, retResellable("apple", 1))
			retWant(t, note.Discounts, retDiscounts("ten", 25, "off", 25))
			retWant(t, note.Amount, 200)
		})

		t.Run("adds up the reversals of a discount over the lines of a return", func(t *testing.T) {
			s := retShop(t, retTenPercent)
			order := s.shipped(retLine("apple", 2), retLine("pear", 1))
			note := s.give(order.ID, retResellable("apple", 1), retResellable("pear", 1))
			retWant(t, note.Lines, []CreditLine{
				{SKU: "apple", Quantity: 1, Amount: 225},
				{SKU: "pear", Quantity: 1, Amount: 900},
			})
			retWant(t, note.Discounts, retDiscounts("ten", 125))
			retWant(t, note.Amount, 1125)
		})

		t.Run("reverses the discount of a coupon", func(t *testing.T) {
			s := retShop(t)
			retMust(t, s.engine.AddCoupon(Coupon{
				Code:       "SAVE20",
				Promotion:  Promotion{ID: "save-twenty", Kind: "percentage", Percent: 20},
				ExpiresOn:  "2026-12-31",
				UsageLimit: 1,
			}))
			cart := NewCart()
			retMust(t, cart.Add("apple", 2))
			order, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: cart, PaymentToken: "card", Coupons: []string{"SAVE20"}})
			retMust(t, err)
			retMust(t, s.orders.Ship(order.ID))
			note := s.give(order.ID, retResellable("apple", 1))
			retWant(t, note.Amount, 200)
			retWant(t, note.Discounts, retDiscounts("save-twenty", 50))
		})
	})

	t.Run("payments", func(t *testing.T) {
		t.Run("refunds the amount of each credit note to the payment of the order", func(t *testing.T) {
			s := retShop(t, retTenPercent)
			order := s.shipped(retLine("apple", 4))
			s.give(order.ID, retResellable("apple", 1))
			s.give(order.ID, retDamaged("apple", 2))
			retWant(t, s.payments.Refunds(), []Refund{
				{PaymentID: order.PaymentID, Amount: 225},
				{PaymentID: order.PaymentID, Amount: 450},
			})
		})

		t.Run("refunds the whole payment once every unit is back", func(t *testing.T) {
			s := retShop(t, Promotion{ID: "fifteen", Kind: "percentage", Percent: 15})
			order := s.shipped(retLine("apple", 3), retLine("pear", 1))
			s.give(order.ID, retResellable("apple", 2))
			s.give(order.ID, retResellable("apple", 1), retResellable("pear", 1))
			retWant(t, retRefunded(s.payments), order.Total)
		})

		t.Run("refunds nothing for units that cost nothing", func(t *testing.T) {
			// 250 off takes the whole price of the apple line.
			s := retShop(t, Promotion{ID: "off", Kind: "fixed", Amount: 250})
			order := s.shipped(retLine("apple", 1), retLine("pear", 1))
			note := s.give(order.ID, retResellable("apple", 1))
			retWant(t, note.Lines, []CreditLine{{SKU: "apple", Quantity: 1, Amount: 0}})
			retWant(t, note.Discounts, retDiscounts("off", 250))
			retWant(t, note.Amount, 0)
			retWant(t, s.payments.Refunds(), []Refund{})
		})
	})

	t.Run("orders", func(t *testing.T) {
		t.Run("keeps an order shipped while it has units left to return", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 2), retLine("pear", 1))
			s.give(order.ID, retResellable("apple", 2))
			retWant(t, retStatus(t, s.orders, order.ID), OrderStatus("shipped"))
		})

		t.Run("marks an order returned once every unit is back", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 2), retLine("pear", 1))
			s.give(order.ID, retResellable("apple", 1))
			s.give(order.ID, retResellable("pear", 1), retDamaged("apple", 1))
			retWant(t, retStatus(t, s.orders, order.ID), OrderStatus("returned"))
			var ids []string
			for _, o := range s.orders.WithStatus("returned") {
				ids = append(ids, o.ID)
			}
			retWant(t, ids, []string{order.ID})
			retWant(t, s.orders.WithStatus("shipped"), []Order{})
		})

		t.Run("rejects a change to a returned order", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 1))
			s.give(order.ID, retResellable("apple", 1))
			want := fmt.Sprintf("order %s is returned", order.ID)
			retWantError(t, s.orders.Ship(order.ID), want)
			retWantError(t, s.orders.Cancel(order.ID), want)
			_, err := s.returns.ReturnItems(order.ID, []ReturnLine{retResellable("apple", 1)})
			retWantError(t, err, want)
		})

		t.Run("takes the credit notes off the revenue", func(t *testing.T) {
			s := retShop(t, retTenPercent)
			s.place(retLine("pear", 1))             // 900
			order := s.shipped(retLine("apple", 4)) // 900
			s.give(order.ID, retResellable("apple", 1))
			retWant(t, s.orders.Revenue(), 1575)
		})

		t.Run("counts the units returned out of the best sellers", func(t *testing.T) {
			s := retShop(t)
			first := s.shipped(retLine("apple", 3), retLine("pear", 2))
			second := s.shipped(retLine("pear", 1))
			s.give(first.ID, retResellable("apple", 2))
			s.give(second.ID, retResellable("pear", 1))
			retWant(t, s.orders.BestSellers(5), []SKUSales{{SKU: "pear", Quantity: 2}, {SKU: "apple", Quantity: 1}})
			s.give(first.ID, retResellable("apple", 1))
			retWant(t, s.orders.BestSellers(5), []SKUSales{{SKU: "pear", Quantity: 2}})
		})
	})

	t.Run("the return window", func(t *testing.T) {
		t.Run("accepts a return up to and including 30 days after the order was placed", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 2))
			s.clock.Set("2026-04-09")
			retWant(t, s.give(order.ID, retResellable("apple", 1)).Amount, 250)
		})

		t.Run("rejects a return after the return window", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 2))
			s.clock.Set("2026-04-10")
			_, err := s.returns.ReturnItems(order.ID, []ReturnLine{retResellable("apple", 1)})
			retWantError(t, err, fmt.Sprintf("the return window of order %s has closed", order.ID))
		})
	})

	t.Run("errors", func(t *testing.T) {
		// rejects runs a return that must fail with the error want.
		rejects := func(t *testing.T, s retFixture, orderID string, want string, lines ...ReturnLine) {
			t.Helper()
			_, err := s.returns.ReturnItems(orderID, lines)
			retWantError(t, err, want)
		}

		t.Run("rejects a return of an unknown order", func(t *testing.T) {
			s := retShop(t)
			rejects(t, s, "no-such-order", "unknown order no-such-order", retResellable("apple", 1))
			_, err := s.returns.CreditNotes("no-such-order")
			retWantError(t, err, "unknown order no-such-order")
		})

		t.Run("rejects a return of an order that has not shipped", func(t *testing.T) {
			s := retShop(t)
			order := s.place(retLine("apple", 2))
			rejects(t, s, order.ID, fmt.Sprintf("order %s is paid", order.ID), retResellable("apple", 1))
		})

		t.Run("rejects a return of a cancelled order", func(t *testing.T) {
			s := retShop(t)
			order := s.place(retLine("apple", 2))
			retMust(t, s.orders.Cancel(order.ID))
			rejects(t, s, order.ID, fmt.Sprintf("order %s is cancelled", order.ID), retResellable("apple", 1))
		})

		t.Run("rejects a return with no lines", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 2))
			rejects(t, s, order.ID, "nothing to return")
		})

		t.Run("rejects a SKU that is not in the order", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 2))
			rejects(t, s, order.ID, fmt.Sprintf("SKU pear is not in order %s", order.ID), retResellable("pear", 1))
		})

		t.Run("rejects a quantity below 1", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 2))
			rejects(t, s, order.ID, "quantity must be at least 1", retResellable("apple", 0))
		})

		t.Run("rejects more units than are left to return", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 3))
			s.give(order.ID, retResellable("apple", 2))
			rejects(t, s, order.ID, "apple has 1 left to return", retResellable("apple", 2))
		})

		t.Run("rejects a SKU in more than one line", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 3))
			rejects(t, s, order.ID, "SKU apple is in more than one line",
				retResellable("apple", 1), retDamaged("apple", 1))
		})

		t.Run("rejects an unknown condition", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 3))
			rejects(t, s, order.ID, "unknown condition broken",
				ReturnLine{SKU: "apple", Quantity: 1, Condition: "broken"})
		})

		t.Run("changes nothing when a return fails", func(t *testing.T) {
			s := retShop(t)
			order := s.shipped(retLine("apple", 3), retLine("pear", 1))
			rejects(t, s, order.ID, "pear has 1 left to return",
				retResellable("apple", 1), retResellable("pear", 2))
			retWant(t, s.inventory.Available("apple"), 17)
			retWant(t, s.payments.Refunds(), []Refund{})
			retWant(t, retCreditNotes(t, s.returns, order.ID), []CreditNote{})
			retWant(t, retStatus(t, s.orders, order.ID), OrderStatus("shipped"))
			retWant(t, s.give(order.ID, retResellable("apple", 3)).Amount, 750)
		})
	})
}
