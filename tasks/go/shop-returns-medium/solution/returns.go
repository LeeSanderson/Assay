// Returns: partial returns of shipped orders, and their credit notes.

package shop

import (
	"shop/domain"
	"shop/services"
)

type (
	CreditLine    = domain.CreditLine
	CreditNote    = domain.CreditNote
	ItemCondition = domain.ItemCondition
	ReturnLine    = domain.ReturnLine
	Returns       = services.Returns
	ReturnsDeps   = services.ReturnsDeps
)

var (
	NewReturns = services.NewReturns
)
