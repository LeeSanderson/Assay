// Shipping: the shipments of the orders, their rates and their labels.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	Shipment                   = domain.Shipment
	ShipmentRepository         = domain.ShipmentRepository
	ShipmentStatus             = domain.ShipmentStatus
	ShippingRate               = domain.ShippingRate
	Zone                       = domain.Zone
	InMemoryShipmentRepository = adapters.InMemoryShipmentRepository
	ShippingDeps               = services.ShippingDeps
	Shipping                   = services.Shipping
)

var (
	NewInMemoryShipmentRepository = adapters.NewInMemoryShipmentRepository
	PackingSlip                   = adapters.PackingSlip
	ShippingLabel                 = adapters.ShippingLabel
	NewShipping                   = services.NewShipping
)
