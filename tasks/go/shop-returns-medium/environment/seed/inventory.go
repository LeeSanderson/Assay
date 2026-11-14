// The inventory: the stock of each SKU, its reservations and its movements.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	BalanceLine             = domain.BalanceLine
	Reservation             = domain.Reservation
	StockLevel              = domain.StockLevel
	StockLine               = domain.StockLine
	StockMovement           = domain.StockMovement
	StockRepository         = domain.StockRepository
	Variance                = domain.Variance
	InMemoryStockRepository = adapters.InMemoryStockRepository
	Inventory               = services.Inventory
)

var (
	NewInMemoryStockRepository = adapters.NewInMemoryStockRepository
	NewInventory               = services.NewInventory
)
