// Invoices: one for each order that is not cancelled, and their text.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	Invoice                   = domain.Invoice
	InvoiceLine               = domain.InvoiceLine
	InvoiceRepository         = domain.InvoiceRepository
	InMemoryInvoiceRepository = adapters.InMemoryInvoiceRepository
	InvoicingDeps             = services.InvoicingDeps
	TaxSummary                = services.TaxSummary
	Invoicing                 = services.Invoicing
)

var (
	NewInMemoryInvoiceRepository = adapters.NewInMemoryInvoiceRepository
	InvoiceText                  = adapters.InvoiceText
	NewInvoicing                 = services.NewInvoicing
)
