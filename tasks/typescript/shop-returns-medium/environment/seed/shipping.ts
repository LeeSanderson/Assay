// Shipping: the shipments of the orders, their rates and their labels.

export type {
  Shipment,
  ShipmentRepository,
  ShipmentStatus,
  ShippingRate,
  Zone,
} from './domain/shipment.ts'
export { InMemoryShipmentRepository } from './adapters/memory.ts'
export { packingSlip, shippingLabel } from './adapters/text.ts'
export type { ShippingDeps } from './services/shipping.ts'
export { Shipping } from './services/shipping.ts'
