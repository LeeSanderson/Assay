// The inventory: the stock of each SKU, its reservations and its movements.

export type {
  BalanceLine,
  Reservation,
  StockLevel,
  StockLine,
  StockMovement,
  StockRepository,
  Variance,
} from './domain/stock.ts'
export { InMemoryStockRepository } from './adapters/memory.ts'
export { Inventory } from './services/inventory.ts'
