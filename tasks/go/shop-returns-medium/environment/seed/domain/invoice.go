// Invoices. The shop issues one invoice for an order that is not cancelled.
// An invoice copies the lines, the discounts and the total of the order as
// placed, and shows the tax that the total includes, at the tax rate of the
// shop. Invoices have their own number, with no gaps: INV-000001, INV-000002.

package domain

import (
	"fmt"
	"slices"
)

type InvoiceLine struct {
	SKU         string
	Description string
	Quantity    int
	UnitPrice   Cents
	Amount      Cents
}

type Invoice struct {
	ID         string
	Number     string
	OrderID    string
	CustomerID string
	Lines      []InvoiceLine
	Subtotal   Cents
	Discounts  []Discount
	Total      Cents // what the customer paid, tax included
	TaxRate    int   // in basis points: 2000 is 20%
	Tax        Cents // the tax that the total includes
	IssuedOn   IsoDate
}

type InvoiceRepository interface {
	Get(id string) (Invoice, bool)
	Save(invoice Invoice)
	List() []Invoice // in the order that they were issued
}

// StandardTaxRate is the tax rate of the shop, in basis points.
const StandardTaxRate = 2000

func InvoiceNumber(sequence int) string { return fmt.Sprintf("INV-%06d", sequence) }

// InvoiceOf gives the invoice of an order. It names each field of the order
// that it copies.
func InvoiceOf(order Order, id, number string, taxRate int, issuedOn IsoDate) (Invoice, error) {
	tax, err := IncludedTax(order.Total, taxRate)
	if err != nil {
		return Invoice{}, err
	}
	lines := []InvoiceLine{}
	for _, line := range order.Lines {
		lines = append(lines, InvoiceLine{line.SKU, line.Name, line.Quantity, line.UnitPrice,
			Times(line.UnitPrice, line.Quantity)})
	}
	return Invoice{ID: id, Number: number, OrderID: order.ID, CustomerID: order.CustomerID,
		Lines: lines, Subtotal: order.Subtotal, Discounts: slices.Clone(order.Discounts),
		Total: order.Total, TaxRate: taxRate, Tax: tax, IssuedOn: issuedOn}, nil
}

func CopyInvoice(invoice Invoice) Invoice {
	invoice.Lines = slices.Clone(invoice.Lines)
	invoice.Discounts = slices.Clone(invoice.Discounts)
	return invoice
}
