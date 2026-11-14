// The cart: the SKUs that a customer wants and how many of each, in the order
// that the customer first added them.

export interface CartLine {
  sku: string
  quantity: number
}

export class Cart {
  private readonly items: CartLine[] = []

  public add(sku: string, quantity: number): void {
    checkQuantity(quantity)
    const line = this.items.find((item) => item.sku === sku)
    if (line === undefined) {
      this.items.push({ sku, quantity })
    } else {
      line.quantity += quantity
    }
  }

  public setQuantity(sku: string, quantity: number): void {
    checkQuantity(quantity)
    this.line(sku).quantity = quantity
  }

  public remove(sku: string): void {
    const line = this.line(sku)
    this.items.splice(this.items.indexOf(line), 1)
  }

  public lines(): CartLine[] {
    return this.items.map((item) => ({ ...item }))
  }

  public isEmpty(): boolean {
    return this.items.length === 0
  }

  // The number of units in the cart, over all its lines.
  public itemCount(): number {
    return this.items.reduce((sum, item) => sum + item.quantity, 0)
  }

  public clear(): void {
    this.items.length = 0
  }

  private line(sku: string): CartLine {
    const line = this.items.find((item) => item.sku === sku)
    if (line === undefined) {
      throw new Error(`SKU ${sku} is not in the cart`)
    }
    return line
  }
}

function checkQuantity(quantity: number): void {
  if (quantity < 1) {
    throw new Error('quantity must be at least 1')
  }
}
