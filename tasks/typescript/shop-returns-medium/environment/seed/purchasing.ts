// Purchasing: the suppliers and the purchase orders that bring stock in.

export type {
  PurchaseLine,
  PurchaseOrder,
  PurchaseRepository,
  PurchaseStatus,
  Supplier,
  SupplierRepository,
} from './domain/purchase.ts'
export { InMemoryPurchaseRepository, InMemorySupplierRepository } from './adapters/memory.ts'
export type { PurchasingDeps } from './services/purchasing.ts'
export { Purchasing } from './services/purchasing.ts'
