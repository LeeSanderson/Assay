// Orders: what the checkout placed, and what happens to an order after it.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	Order                   = domain.Order
	OrderFilter             = domain.OrderFilter
	OrderLine               = domain.OrderLine
	OrderRepository         = domain.OrderRepository
	OrderStatus             = domain.OrderStatus
	SKUSales                = domain.SKUSales
	InMemoryOrderRepository = adapters.InMemoryOrderRepository
	Orders                  = services.Orders
)

var (
	NewInMemoryOrderRepository = adapters.NewInMemoryOrderRepository
	NewOrders                  = services.NewOrders
)
