// Invoicing: the shop issues one invoice for each order that is not
// cancelled, on request, numbered in the order of issue.

package services

import (
	"fmt"
	"slices"

	. "shop/domain"
)

type InvoicingDeps struct {
	Invoices InvoiceRepository
	Orders   *Orders
	Clock    Clock
	IDs      IDSource
	TaxRate  *int // in basis points; StandardTaxRate when nil
}

// TaxSummary is the tax of a period: the invoices issued in it and the tax
// that they hold.
type TaxSummary struct {
	From     IsoDate
	To       IsoDate
	Invoices int
	Total    Cents
	Tax      Cents
}

type Invoicing struct {
	deps    InvoicingDeps
	taxRate int
}

func NewInvoicing(deps InvoicingDeps) (*Invoicing, error) {
	invoicing := &Invoicing{deps: deps, taxRate: StandardTaxRate}
	if deps.TaxRate != nil {
		invoicing.taxRate = *deps.TaxRate
	}
	if invoicing.taxRate < 0 {
		return nil, Invalid("tax rate must be a whole number of basis points")
	}
	return invoicing, nil
}

func (i *Invoicing) Issue(orderID string) (Invoice, error) {
	order, err := i.deps.Orders.Order(orderID)
	if err == nil && !Counts(order) {
		err = WrongState("order", order.ID, string(order.Status))
	}
	if _, found := i.find(orderID); err == nil && found {
		err = Conflict(fmt.Sprintf("order %s already has an invoice", orderID))
	}
	if err != nil {
		return Invoice{}, err
	}
	invoice, _ := InvoiceOf(order, i.deps.IDs.Next(Prefix.Invoice),
		InvoiceNumber(len(i.deps.Invoices.List())+1), i.taxRate, i.deps.Clock.Today())
	i.deps.Invoices.Save(invoice)
	return invoice, nil
}

// IssueOutstanding issues the invoice of each order that counts and has
// none, in the order that the orders were placed, and gives the new
// invoices.
func (i *Invoicing) IssueOutstanding() []Invoice {
	issued := []Invoice{}
	for _, orderID := range i.Uninvoiced() {
		invoice, _ := i.Issue(orderID) // an order that counts and has no invoice
		issued = append(issued, invoice)
	}
	return issued
}

func (i *Invoicing) Invoice(id string) (Invoice, error) {
	if invoice, ok := i.deps.Invoices.Get(id); ok {
		return invoice, nil
	}
	return Invoice{}, NotFound("invoice", id)
}

// InvoiceFor gives the invoice of an order: an error when it has none.
func (i *Invoicing) InvoiceFor(orderID string) (Invoice, error) {
	_, err := i.deps.Orders.Order(orderID)
	invoice, found := i.find(orderID)
	if err == nil && !found {
		err = Invalid(fmt.Sprintf("order %s has no invoice", orderID))
	}
	return invoice, err
}

func (i *Invoicing) ByNumber(number string) (Invoice, error) {
	invoices := i.deps.Invoices.List()
	if at := slices.IndexFunc(invoices, func(invoice Invoice) bool { return invoice.Number == number }); at >= 0 {
		return invoices[at], nil
	}
	return Invoice{}, NotFound("invoice", number)
}

func (i *Invoicing) IssuedBetween(from, to IsoDate) ([]Invoice, error) {
	if err := CheckPeriod(from, to); err != nil {
		return nil, err
	}
	return slices.DeleteFunc(i.deps.Invoices.List(), func(invoice Invoice) bool {
		return !Within(invoice.IssuedOn, from, to)
	}), nil
}

func (i *Invoicing) TaxSummary(from, to IsoDate) (TaxSummary, error) {
	invoices, err := i.IssuedBetween(from, to)
	summary := TaxSummary{From: from, To: to, Invoices: len(invoices)}
	for _, invoice := range invoices {
		summary.Total += invoice.Total
		summary.Tax += invoice.Tax
	}
	return summary, err
}

// CancelledAfterIssue gives the invoices whose orders were cancelled after
// the invoice was issued, which the accountant must cancel by hand, in the
// order of issue.
func (i *Invoicing) CancelledAfterIssue() []Invoice {
	return slices.DeleteFunc(i.deps.Invoices.List(), func(invoice Invoice) bool {
		order, _ := i.deps.Orders.Order(invoice.OrderID)
		return Counts(order)
	})
}

// Uninvoiced gives the orders that count and have no invoice yet, by id, in
// the order that they were placed.
func (i *Invoicing) Uninvoiced() []string {
	ids := []string{}
	for _, order := range i.deps.Orders.All() {
		if _, found := i.find(order.ID); Counts(order) && !found {
			ids = append(ids, order.ID)
		}
	}
	return ids
}

func (i *Invoicing) find(orderID string) (Invoice, bool) {
	invoices := i.deps.Invoices.List()
	at := slices.IndexFunc(invoices, func(invoice Invoice) bool { return invoice.OrderID == orderID })
	if at < 0 {
		return Invoice{}, false
	}
	return invoices[at], true
}
