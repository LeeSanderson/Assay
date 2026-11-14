// Returns: a customer sends back units of a shipped order. Each return issues
// a credit note, which refunds what the customer paid for those units: their
// price less their share of each discount of the order.

package shop

import (
	"errors"
	"fmt"
	"slices"
	"time"
)

type ItemCondition string // "resellable" or "damaged"

type ReturnLine struct {
	SKU       string
	Quantity  int
	Condition ItemCondition
}

type CreditLine struct {
	SKU      string
	Quantity int
	Amount   int
}

type CreditNote struct {
	ID        string
	OrderID   string
	Lines     []CreditLine
	Discounts []Discount
	Amount    int
	IssuedOn  string
}

type ReturnsDeps struct {
	Orders    OrderRepository
	Inventory *Inventory
	Payments  PaymentGateway
	Clock     Clock
	IDs       IDSource
}

type Returns struct {
	deps ReturnsDeps
}

const returnDays = 30

func NewReturns(deps ReturnsDeps) *Returns {
	return &Returns{deps: deps}
}

// ReturnItems returns the units of the lines, or none of them, and issues
// their credit note.
func (r *Returns) ReturnItems(orderID string, lines []ReturnLine) (CreditNote, error) {
	order, err := r.order(orderID)
	if err != nil {
		return CreditNote{}, err
	}
	if order.Status != "shipped" {
		return CreditNote{}, fmt.Errorf("order %s is %s", orderID, order.Status)
	}
	if err := checkWindow(order, r.deps.Clock.Today()); err != nil {
		return CreditNote{}, err
	}
	if len(lines) == 0 {
		return CreditNote{}, errors.New("nothing to return")
	}
	for i, line := range lines {
		ordered, ok := orderLine(order, line.SKU)
		switch {
		case !ok:
			return CreditNote{}, fmt.Errorf("SKU %s is not in order %s", line.SKU, orderID)
		case slices.ContainsFunc(lines[:i], func(l ReturnLine) bool { return l.SKU == line.SKU }):
			return CreditNote{}, fmt.Errorf("SKU %s is in more than one line", line.SKU)
		case line.Quantity < 1:
			return CreditNote{}, errors.New("quantity must be at least 1")
		case line.Condition != "resellable" && line.Condition != "damaged":
			return CreditNote{}, fmt.Errorf("unknown condition %s", line.Condition)
		}
		if left := ordered.Quantity - returnedUnits(order, line.SKU); line.Quantity > left {
			return CreditNote{}, fmt.Errorf("%s has %d left to return", line.SKU, left)
		}
	}

	note := r.creditNote(order, lines)
	if note.Amount > 0 && order.PaymentID != "" {
		if _, err := r.deps.Payments.RefundPart(order.PaymentID, note.Amount); err != nil {
			return CreditNote{}, err
		}
	}
	for _, line := range lines {
		if line.Condition == "resellable" {
			_ = r.deps.Inventory.Restock(line.SKU, line.Quantity) // the quantity is at least 1
		}
	}
	order.CreditNotes = append(order.CreditNotes, note)
	returned := true
	for _, line := range order.Lines {
		returned = returned && returnedUnits(order, line.SKU) == line.Quantity
	}
	if returned {
		order.Status = "returned"
	}
	r.deps.Orders.Save(order)
	return note, nil
}

// CreditNotes gives the credit notes of the order, in the order that they
// were issued.
func (r *Returns) CreditNotes(orderID string) ([]CreditNote, error) {
	order, err := r.order(orderID)
	if err != nil {
		return nil, err
	}
	return order.CreditNotes, nil
}

func (r *Returns) order(id string) (Order, error) {
	order, ok := r.deps.Orders.Get(id)
	if !ok {
		return Order{}, fmt.Errorf("unknown order %s", id)
	}
	return order, nil
}

func checkWindow(order Order, today string) error {
	placed, err := time.Parse(time.DateOnly, order.PlacedOn)
	if err != nil {
		return err
	}
	if today > placed.AddDate(0, 0, returnDays).Format(time.DateOnly) {
		return fmt.Errorf("the return window of order %s has closed", order.ID)
	}
	return nil
}

func orderLine(order Order, sku string) (OrderLine, bool) {
	for _, line := range order.Lines {
		if line.SKU == sku {
			return line, true
		}
	}
	return OrderLine{}, false
}

// creditNote reverses each discount on a line in proportion to the units
// returned: after r of q units in all, floor(part * r / q) of it.
func (r *Returns) creditNote(order Order, lines []ReturnLine) CreditNote {
	note := CreditNote{ID: r.deps.IDs.Next("credit"), OrderID: order.ID, IssuedOn: r.deps.Clock.Today()}
	reversed := map[string]int{}
	for _, line := range lines {
		ordered, _ := orderLine(order, line.SKU)
		before := returnedUnits(order, line.SKU)
		after := before + line.Quantity
		amount := ordered.UnitPrice * line.Quantity
		for _, part := range ordered.Discounts {
			share := part.Amount*after/ordered.Quantity - part.Amount*before/ordered.Quantity
			amount -= share
			reversed[part.PromotionID] += share
		}
		note.Lines = append(note.Lines, CreditLine{SKU: line.SKU, Quantity: line.Quantity, Amount: amount})
		note.Amount += amount
	}
	for _, discount := range order.Discounts {
		if amount := reversed[discount.PromotionID]; amount > 0 {
			note.Discounts = append(note.Discounts, Discount{PromotionID: discount.PromotionID, Amount: amount})
		}
	}
	return note
}
