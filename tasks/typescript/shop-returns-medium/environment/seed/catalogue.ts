// The catalogue: the products that the shop sells, by SKU, and their prices.

export type {
  ImportResult,
  PriceChange,
  Product,
  ProductRepository,
  ProductRow,
} from './domain/product.ts'
export { InMemoryProductRepository } from './adapters/memory.ts'
export { productRows } from './adapters/csv.ts'
export { Catalogue } from './services/catalogue.ts'
