// Returns: a customer sends back units of a shipped order, up to 30 days
// after it was placed. Each return issues a credit note, which refunds what
// the customer paid for those units: their price, less their share of each
// discount of the order. A return reverses each part of a discount on a line
// in proportion to the units of that line that come back.

package domain

import (
	"fmt"
	"slices"
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
	Amount   Cents // what the credit note refunds for these units
}

type CreditNote struct {
	ID        string
	OrderID   string
	Lines     []CreditLine
	Discounts []Discount // the part of each discount of the order that the return reverses
	Amount    Cents      // the sum of the amounts of the lines
	IssuedOn  IsoDate
}

const ReturnDays = 30

// CheckReturn checks that the lines can come back from the order on the
// date: the order is shipped, the return window is open, and each line names
// a SKU of the order once, with a quantity that is still left to return.
func CheckReturn(order Order, lines []ReturnLine, today IsoDate) error {
	if order.Status != "shipped" {
		return WrongState("order", order.ID, string(order.Status))
	}
	if DaysBetween(order.PlacedOn, today) > ReturnDays {
		return Invalid(fmt.Sprintf("the return window of order %s has closed", order.ID))
	}
	if len(lines) == 0 {
		return Invalid("nothing to return")
	}
	for i, line := range lines {
		ordered, ok := orderLine(order, line.SKU)
		switch {
		case !ok:
			return Invalid(fmt.Sprintf("SKU %s is not in order %s", line.SKU, order.ID))
		case slices.ContainsFunc(lines[:i], func(l ReturnLine) bool { return l.SKU == line.SKU }):
			return Invalid(fmt.Sprintf("SKU %s is in more than one line", line.SKU))
		}
		if err := CheckQuantity(line.Quantity); err != nil {
			return err
		}
		if line.Condition != "resellable" && line.Condition != "damaged" {
			return Invalid(fmt.Sprintf("unknown condition %s", line.Condition))
		}
		if left := ordered.Quantity - ReturnedUnits(order, line.SKU); line.Quantity > left {
			return Invalid(fmt.Sprintf("%s has %d left to return", line.SKU, left))
		}
	}
	return nil
}

// CreditFor gives what a return of the lines refunds, without its id and
// date: each part of a discount on a line, after r of its q units in all have
// come back, is reversed to floor(part * r / q), so this return reverses the
// difference. The lines must have passed CheckReturn.
func CreditFor(order Order, lines []ReturnLine) CreditNote {
	note := CreditNote{OrderID: order.ID}
	reversed := map[string]Cents{}
	for _, line := range lines {
		ordered, _ := orderLine(order, line.SKU)
		before := ReturnedUnits(order, line.SKU)
		after := before + line.Quantity
		amount := Times(ordered.UnitPrice, line.Quantity)
		for _, part := range ordered.Discounts {
			// The quantity of an order line is at least 1, so neither share fails.
			now, _ := ShareOf(part.Amount, after, ordered.Quantity)
			was, _ := ShareOf(part.Amount, before, ordered.Quantity)
			amount -= now - was
			reversed[part.PromotionID] += now - was
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

// WithCreditNote gives the order with the credit note added; returned once
// every unit of every line has come back.
func WithCreditNote(order Order, note CreditNote) Order {
	order = CopyOrder(order)
	order.CreditNotes = append(order.CreditNotes, note)
	returned := true
	for _, line := range order.Lines {
		returned = returned && ReturnedUnits(order, line.SKU) == line.Quantity
	}
	if returned {
		order.Status = "returned"
	}
	return order
}

func orderLine(order Order, sku string) (OrderLine, bool) {
	i := slices.IndexFunc(order.Lines, func(line OrderLine) bool { return line.SKU == sku })
	if i < 0 {
		return OrderLine{}, false
	}
	return order.Lines[i], true
}
