// The receipt of an order, as plain text, and the format of an amount.

package shop

import (
	"shop/adapters"
	"shop/domain"
)

var (
	FormatCents = domain.FormatCents
	Receipt     = adapters.Receipt
)
