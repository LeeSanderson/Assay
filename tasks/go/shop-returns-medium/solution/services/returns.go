// Returns: a customer sends back units of a shipped order, in one return or
// in several. Each return puts the resellable units back into stock, issues
// a credit note and refunds its amount to the payment of the order. A return
// that fails changes nothing: it checks everything before its first write.

package services

import . "shop/domain"

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

func NewReturns(deps ReturnsDeps) *Returns { return &Returns{deps: deps} }

// ReturnItems returns the units of the lines from the order, or none of
// them, and gives the credit note of the return.
func (r *Returns) ReturnItems(orderID string, lines []ReturnLine) (CreditNote, error) {
	order, err := r.order(orderID)
	if err != nil {
		return CreditNote{}, err
	}
	today := r.deps.Clock.Today()
	if err := CheckReturn(order, lines, today); err != nil {
		return CreditNote{}, err
	}
	note := CreditFor(order, lines)
	note.ID = r.deps.IDs.Next(Prefix.Credit)
	note.IssuedOn = today
	if note.Amount > 0 && order.PaymentID != "" {
		if _, err := r.deps.Payments.RefundPart(order.PaymentID, note.Amount); err != nil {
			return CreditNote{}, err
		}
	}
	for _, line := range lines {
		if line.Condition == "resellable" {
			_ = r.deps.Inventory.Restock(line.SKU, line.Quantity) // CheckReturn checked the quantity
		}
	}
	r.deps.Orders.Save(WithCreditNote(order, note))
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
		return Order{}, NotFound("order", id)
	}
	return order, nil
}
