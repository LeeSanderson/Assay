// The catalogue: the products that the shop sells, by SKU, and their prices.

import { conflict, isShopError, notFound } from '../domain/errors.ts'
import { compareText } from '../domain/ids.ts'
import type { Cents } from '../domain/money.ts'
import { checkName, checkPrice, newProduct, productOfRow } from '../domain/product.ts'
import type {
  ImportResult,
  PriceChange,
  Product,
  ProductRepository,
  ProductRow,
} from '../domain/product.ts'

export class Catalogue {
  private readonly changes: PriceChange[] = []

  constructor(private readonly repository: ProductRepository) {}

  public addProduct(sku: string, name: string, unitPrice: Cents): Product {
    const product = newProduct(sku, name, unitPrice)
    if (this.repository.get(sku) !== undefined) {
      throw conflict(`product ${sku} already exists`)
    }
    this.repository.save(product)
    return { ...product }
  }

  public product(sku: string): Product {
    const product = this.repository.get(sku)
    if (product === undefined) {
      throw notFound('product', sku)
    }
    return product
  }

  // Whether the catalogue holds the SKU, on sale or not.
  public has(sku: string): boolean {
    return this.repository.get(sku) !== undefined
  }

  public changePrice(sku: string, unitPrice: Cents): void {
    const product = this.product(sku)
    checkPrice(unitPrice)
    if (unitPrice === product.unitPrice) {
      return
    }
    this.repository.save({ ...product, unitPrice })
    this.changes.push({ sku, from: product.unitPrice, to: unitPrice })
  }

  // The price changes of one SKU, oldest first.
  public priceHistory(sku: string): PriceChange[] {
    this.product(sku)
    return this.changes.filter((change) => change.sku === sku).map((c) => ({ ...c }))
  }

  // Changes the price of each product on sale by `percent` per cent (a
  // negative percent lowers it), rounded down to a whole cent, and never
  // below 1 cent. It gives the products that it changed, in SKU order.
  public reprice(percent: number, skus: readonly string[] = []): Product[] {
    const changed: Product[] = []
    const products = this.activeProducts().filter(
      (product) => skus.length === 0 || skus.includes(product.sku)
    )
    for (const product of products) {
      const unitPrice = Math.max(1, Math.floor((product.unitPrice * (100 + percent)) / 100))
      if (unitPrice !== product.unitPrice) {
        this.changePrice(product.sku, unitPrice)
        changed.push(this.product(product.sku))
      }
    }
    return changed
  }

  // Imports a price list: a row with a new SKU adds a product, a row with a
  // known SKU sets its name and price, and a broken row is rejected and
  // changes nothing. A SKU on two rows is rejected the second time.
  public importProducts(rows: readonly ProductRow[]): ImportResult {
    const result: ImportResult = { added: [], updated: [], rejected: [] }
    const seen = new Set<string>()
    rows.forEach((row, index) => {
      try {
        const product = productOfRow(row)
        if (seen.has(product.sku)) {
          throw conflict(`SKU ${product.sku} is on more than one row`)
        }
        seen.add(product.sku)
        const known = this.repository.get(product.sku)
        if (known === undefined) {
          this.repository.save(product)
          result.added.push(product.sku)
        } else if (known.name !== product.name || known.unitPrice !== product.unitPrice) {
          this.rename(product.sku, product.name)
          this.changePrice(product.sku, product.unitPrice)
          result.updated.push(product.sku)
        }
      } catch (error) {
        if (!isShopError(error)) throw error
        result.rejected.push({ row: index + 1, reason: error.message })
      }
    })
    return result
  }

  public rename(sku: string, name: string): void {
    const product = this.product(sku)
    checkName(name)
    this.repository.save({ ...product, name })
  }

  // The products on sale whose name holds the text, in any case, in SKU order.
  public search(text: string): Product[] {
    const wanted = text.toLowerCase()
    return this.activeProducts().filter((product) =>
      product.name.toLowerCase().includes(wanted)
    )
  }

  public discontinue(sku: string): void {
    const product = this.product(sku)
    this.repository.save({ ...product, discontinued: true })
  }

  // Puts a discontinued product back on sale.
  public reinstate(sku: string): void {
    const product = this.product(sku)
    this.repository.save({ ...product, discontinued: false })
  }

  // The products on sale, in SKU order.
  public activeProducts(): Product[] {
    return this.repository
      .list()
      .filter((product) => !product.discontinued)
      .sort((a, b) => compareText(a.sku, b.sku))
  }

  // The products on sale whose price is from `least` to `most`, both
  // included, cheapest first, and in SKU order on a tie.
  public inPriceRange(least: Cents, most: Cents): Product[] {
    return this.activeProducts()
      .filter((product) => product.unitPrice >= least && product.unitPrice <= most)
      .sort((a, b) => a.unitPrice - b.unitPrice || compareText(a.sku, b.sku))
  }
}
