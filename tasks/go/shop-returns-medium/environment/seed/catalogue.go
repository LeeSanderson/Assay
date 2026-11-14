// The catalogue: the products that the shop sells, by SKU, and their prices.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	ImportResult              = domain.ImportResult
	PriceChange               = domain.PriceChange
	Product                   = domain.Product
	ProductRepository         = domain.ProductRepository
	ProductRow                = domain.ProductRow
	InMemoryProductRepository = adapters.InMemoryProductRepository
	Catalogue                 = services.Catalogue
)

var (
	NewInMemoryProductRepository = adapters.NewInMemoryProductRepository
	ProductRows                  = adapters.ProductRows
	NewCatalogue                 = services.NewCatalogue
)
