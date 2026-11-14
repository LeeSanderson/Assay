// The catalogue: the products that the shop sells, by SKU, and their prices.
// All amounts are whole cents.

export interface Product {
  sku: string
  name: string
  unitPrice: number
  discontinued: boolean
}

export interface ProductRepository {
  get(sku: string): Product | undefined
  save(product: Product): void
  list(): Product[]
}

export class InMemoryProductRepository implements ProductRepository {
  private readonly products = new Map<string, Product>()

  get(sku: string): Product | undefined {
    const product = this.products.get(sku)
    return product === undefined ? undefined : { ...product }
  }

  save(product: Product): void {
    this.products.set(product.sku, { ...product })
  }

  list(): Product[] {
    return [...this.products.values()].map((product) => ({ ...product }))
  }
}

export class Catalogue {
  constructor(private readonly repository: ProductRepository) {}

  public addProduct(sku: string, name: string, unitPrice: number): Product {
    if (sku.trim() === '') {
      throw new Error('SKU must not be empty')
    }
    if (name.trim() === '') {
      throw new Error('name must not be empty')
    }
    checkPrice(unitPrice)
    if (this.repository.get(sku) !== undefined) {
      throw new Error(`product ${sku} already exists`)
    }
    const product: Product = { sku, name, unitPrice, discontinued: false }
    this.repository.save(product)
    return { ...product }
  }

  public product(sku: string): Product {
    const product = this.repository.get(sku)
    if (product === undefined) {
      throw new Error(`unknown product ${sku}`)
    }
    return product
  }

  public changePrice(sku: string, unitPrice: number): void {
    const product = this.product(sku)
    checkPrice(unitPrice)
    this.repository.save({ ...product, unitPrice })
  }

  public rename(sku: string, name: string): void {
    const product = this.product(sku)
    if (name.trim() === '') {
      throw new Error('name must not be empty')
    }
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

  // The products on sale, in SKU order.
  public activeProducts(): Product[] {
    return this.repository
      .list()
      .filter((product) => !product.discontinued)
      .sort((a, b) => (a.sku < b.sku ? -1 : a.sku > b.sku ? 1 : 0))
  }
}

function checkPrice(unitPrice: number): void {
  if (unitPrice < 1) {
    throw new Error('unit price must be at least 1')
  }
}
