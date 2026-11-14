// The inventory: the stock of each SKU. Stock on hand is either available or
// reserved for an order. A reservation holds stock from checkout until the
// order ships (commit) or is cancelled (release). Each change to the stock on
// hand adds a movement to the log of the store.

import { check, checkQuantity, conflict, invalid } from '../domain/errors.ts'
import { compareText } from '../domain/ids.ts'
import { availableOf, emptyLevel, mergeLines, runningBalance } from '../domain/stock.ts'
import type {
  BalanceLine,
  StockLevel,
  StockLine,
  StockMovement,
  StockRepository,
  Variance,
} from '../domain/stock.ts'

export class Inventory {
  constructor(private readonly repository: StockRepository) {}

  // The movements of one SKU, oldest first.
  public movements(sku: string): StockMovement[] {
    return this.repository.movements().filter((movement) => movement.sku === sku)
  }

  // The SKUs whose available stock is below the threshold, in SKU order.
  public lowStock(threshold: number): StockLevel[] {
    return this.repository
      .list()
      .filter((level) => availableOf(level) < threshold)
      .sort((a, b) => compareText(a.sku, b.sku))
  }

  // Sets the stock on hand after a count. It cannot go below the reserved stock.
  public count(sku: string, onHand: number): void {
    check(Number.isInteger(onHand) && onHand >= 0, 'a count must be at least 0')
    const level = this.level(sku)
    if (onHand < level.reserved) {
      throw invalid(`${sku} has ${level.reserved} reserved`)
    }
    this.repository.save({ ...level, onHand })
    this.move(sku, onHand - level.onHand, 'counted')
  }

  // Counts many SKUs at once, all or none: each count must be at least the
  // reserved stock of its SKU. It gives the variance of each SKU whose count
  // differs from its stock on hand, in the order of the counts.
  public stockTake(counts: readonly StockLine[]): Variance[] {
    const skus = new Set<string>()
    for (const line of counts) {
      check(Number.isInteger(line.quantity) && line.quantity >= 0, 'a count must be at least 0')
      if (skus.has(line.sku)) {
        throw invalid(`SKU ${line.sku} is counted more than once`)
      }
      skus.add(line.sku)
      const level = this.level(line.sku)
      if (line.quantity < level.reserved) {
        throw invalid(`${line.sku} has ${level.reserved} reserved`)
      }
    }
    const variances: Variance[] = []
    for (const line of counts) {
      const expected = this.level(line.sku).onHand
      if (line.quantity !== expected) {
        this.count(line.sku, line.quantity)
        variances.push({
          sku: line.sku,
          expected,
          counted: line.quantity,
          difference: line.quantity - expected,
        })
      }
    }
    return variances
  }

  // The movements of one SKU with its running stock on hand.
  public history(sku: string): BalanceLine[] {
    return runningBalance(this.movements(sku))
  }

  // The SKUs that the store holds a level for, in SKU order.
  public skus(): string[] {
    return this.repository
      .list()
      .map((level) => level.sku)
      .sort(compareText)
  }

  public level(sku: string): StockLevel {
    return this.repository.get(sku) ?? emptyLevel(sku)
  }

  public available(sku: string): number {
    return availableOf(this.level(sku))
  }

  public receive(sku: string, quantity: number): void {
    checkQuantity(quantity)
    const level = this.level(sku)
    this.repository.save({ ...level, onHand: level.onHand + quantity })
    this.move(sku, quantity, 'received')
  }

  // Puts units that a customer returned back into the stock on hand.
  public restock(sku: string, quantity: number): void {
    checkQuantity(quantity)
    const level = this.level(sku)
    this.repository.save({ ...level, onHand: level.onHand + quantity })
    this.move(sku, quantity, 'returned')
  }

  // Takes stock that was lost or spoiled out of the available stock.
  public writeOff(sku: string, quantity: number): void {
    checkQuantity(quantity)
    const available = this.available(sku)
    if (quantity > available) {
      throw invalid(`not enough stock of ${sku}: ${available} available`)
    }
    const level = this.level(sku)
    this.repository.save({ ...level, onHand: level.onHand - quantity })
    this.move(sku, -quantity, 'written-off')
  }

  // Reserves every line for the order, or none of them.
  public reserve(orderId: string, lines: StockLine[]): void {
    if (this.repository.reservation(orderId) !== undefined) {
      throw conflict(`order ${orderId} already has a reservation`)
    }
    for (const line of lines) {
      checkQuantity(line.quantity)
    }
    const merged = mergeLines(lines)
    for (const line of merged) {
      const available = this.available(line.sku)
      if (line.quantity > available) {
        throw invalid(`not enough stock of ${line.sku}: ${available} available`)
      }
    }
    for (const line of merged) {
      const level = this.level(line.sku)
      this.repository.save({ ...level, reserved: level.reserved + line.quantity })
    }
    this.repository.saveReservation({ orderId, lines: merged })
  }

  // The orders that hold stock of the SKU, with how much each holds.
  public reservedFor(sku: string): { orderId: string; quantity: number }[] {
    return this.repository.reservations().flatMap((reservation) =>
      reservation.lines
        .filter((line) => line.sku === sku)
        .map((line) => ({ orderId: reservation.orderId, quantity: line.quantity }))
    )
  }

  // The stock that the order holds, one line for each SKU.
  public reserved(orderId: string): StockLine[] {
    return this.repository.reservation(orderId)?.lines ?? []
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
      this.move(line.sku, -line.quantity, 'shipped')
    }
  }

  private take(orderId: string): StockLine[] {
    const reservation = this.repository.reservation(orderId)
    if (reservation === undefined) {
      throw invalid(`order ${orderId} has no reservation`)
    }
    this.repository.removeReservation(orderId)
    return reservation.lines
  }

  private move(sku: string, quantity: number, reason: string): void {
    this.repository.addMovement({ sku, quantity, reason })
  }
}
