// The inventory: the stock of each SKU. Stock on hand is either available or
// reserved for an order. A reservation holds stock from checkout until the
// order ships (commit) or is cancelled (release).

export interface StockLevel {
  sku: string
  onHand: number
  reserved: number
}

export interface StockLine {
  sku: string
  quantity: number
}

// A change to the stock on hand, with its reason: `received`, `shipped`,
// `counted` (a stock count that set the stock on hand) or `returned`.
export interface StockMovement {
  sku: string
  quantity: number
  reason: string
}

export interface StockRepository {
  get(sku: string): StockLevel | undefined
  save(level: StockLevel): void
  list(): StockLevel[]
}

export class InMemoryStockRepository implements StockRepository {
  private readonly levels = new Map<string, StockLevel>()

  get(sku: string): StockLevel | undefined {
    const level = this.levels.get(sku)
    return level === undefined ? undefined : { ...level }
  }

  save(level: StockLevel): void {
    this.levels.set(level.sku, { ...level })
  }

  list(): StockLevel[] {
    return [...this.levels.values()].map((level) => ({ ...level }))
  }
}

export class Inventory {
  private readonly reservations = new Map<string, StockLine[]>()
  private readonly log: StockMovement[] = []

  constructor(private readonly repository: StockRepository) {}

  // The movements of one SKU, oldest first.
  public movements(sku: string): StockMovement[] {
    return this.log.filter((movement) => movement.sku === sku).map((m) => ({ ...m }))
  }

  // The SKUs whose available stock is below the threshold, in SKU order.
  public lowStock(threshold: number): StockLevel[] {
    return this.repository
      .list()
      .filter((level) => level.onHand - level.reserved < threshold)
      .sort((a, b) => (a.sku < b.sku ? -1 : a.sku > b.sku ? 1 : 0))
  }

  // Sets the stock on hand after a count. It cannot go below the reserved stock.
  public count(sku: string, onHand: number): void {
    const level = this.level(sku)
    if (onHand < level.reserved) {
      throw new Error(`${sku} has ${level.reserved} reserved`)
    }
    this.repository.save({ ...level, onHand })
    this.log.push({ sku, quantity: onHand - level.onHand, reason: 'counted' })
  }

  public level(sku: string): StockLevel {
    return this.repository.get(sku) ?? { sku, onHand: 0, reserved: 0 }
  }

  public available(sku: string): number {
    const level = this.level(sku)
    return level.onHand - level.reserved
  }

  public receive(sku: string, quantity: number): void {
    checkQuantity(quantity)
    const level = this.level(sku)
    this.repository.save({ ...level, onHand: level.onHand + quantity })
    this.log.push({ sku, quantity, reason: 'received' })
  }

  // Puts units that a customer returned back into the stock on hand.
  public restock(sku: string, quantity: number): void {
    checkQuantity(quantity)
    const level = this.level(sku)
    this.repository.save({ ...level, onHand: level.onHand + quantity })
    this.log.push({ sku, quantity, reason: 'returned' })
  }

  // Reserves every line for the order, or none of them.
  public reserve(orderId: string, lines: StockLine[]): void {
    if (this.reservations.has(orderId)) {
      throw new Error(`order ${orderId} already has a reservation`)
    }
    for (const line of lines) {
      checkQuantity(line.quantity)
      const available = this.available(line.sku)
      if (line.quantity > available) {
        throw new Error(`not enough stock of ${line.sku}: ${available} available`)
      }
    }
    for (const line of lines) {
      const level = this.level(line.sku)
      this.repository.save({ ...level, reserved: level.reserved + line.quantity })
    }
    this.reservations.set(orderId, lines.map((line) => ({ ...line })))
  }

  // Gives the reserved stock of the order back to the available stock.
  public release(orderId: string): void {
    for (const line of this.take(orderId)) {
      const level = this.level(line.sku)
      this.repository.save({ ...level, reserved: level.reserved - line.quantity })
    }
  }

  // Takes the reserved stock of the order out of the stock on hand.
  public commit(orderId: string): void {
    for (const line of this.take(orderId)) {
      const level = this.level(line.sku)
      this.repository.save({
        ...level,
        onHand: level.onHand - line.quantity,
        reserved: level.reserved - line.quantity,
      })
      this.log.push({ sku: line.sku, quantity: -line.quantity, reason: 'shipped' })
    }
  }

  private take(orderId: string): StockLine[] {
    const lines = this.reservations.get(orderId)
    if (lines === undefined) {
      throw new Error(`order ${orderId} has no reservation`)
    }
    this.reservations.delete(orderId)
    return lines
  }
}

function checkQuantity(quantity: number): void {
  if (quantity < 1) {
    throw new Error('quantity must be at least 1')
  }
}
