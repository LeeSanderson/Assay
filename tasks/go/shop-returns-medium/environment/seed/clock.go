// The date and the identifiers that the shop uses, behind interfaces so that
// the tests can fix them.

package shop

import (
	"shop/adapters"
	"shop/domain"
)

type (
	Clock         = domain.Clock
	IsoDate       = domain.IsoDate
	IDSource      = domain.IDSource
	FixedClock    = adapters.FixedClock
	SequentialIDs = adapters.SequentialIDs
)

var (
	NewFixedClock    = adapters.NewFixedClock
	NewSequentialIDs = adapters.NewSequentialIDs
)
