// Purchasing: the suppliers and the purchase orders that bring stock in.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	PurchaseLine               = domain.PurchaseLine
	PurchaseOrder              = domain.PurchaseOrder
	PurchaseRepository         = domain.PurchaseRepository
	PurchaseStatus             = domain.PurchaseStatus
	Supplier                   = domain.Supplier
	SupplierRepository         = domain.SupplierRepository
	InMemoryPurchaseRepository = adapters.InMemoryPurchaseRepository
	InMemorySupplierRepository = adapters.InMemorySupplierRepository
	PurchasingDeps             = services.PurchasingDeps
	Purchasing                 = services.Purchasing
)

var (
	NewInMemoryPurchaseRepository = adapters.NewInMemoryPurchaseRepository
	NewInMemorySupplierRepository = adapters.NewInMemorySupplierRepository
	NewPurchasing                 = services.NewPurchasing
)
