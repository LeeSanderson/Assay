// Stock. The stock on hand of a SKU is either available or reserved for an
// order. A reservation holds stock from checkout until the order ships
// (commit) or is cancelled (release). Each change to the stock on hand is a
// movement, with its reason.

import { check } from './errors.ts'

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
// `counted` (a stock count that set the stock on hand), `written-off` (stock
// that was lost or spoiled in the warehouse) or `returned` (resellable units
// that a customer sent back).
export interface StockMovement {
  sku: string
  quantity: number
  reason: string
}

// The stock that an order holds, from its checkout until it ships or is
// cancelled.
export interface Reservation {
  orderId: string
  lines: StockLine[]
}

// The store of the stock: the level of each SKU, the reservations of the
// orders, and the movements, oldest first.
export interface StockRepository {
  get(sku: string): StockLevel | undefined
  save(level: StockLevel): void
  list(): StockLevel[]
  reservation(orderId: string): Reservation | undefined
  reservations(): Reservation[] // in the order that they were made
  saveReservation(reservation: Reservation): void
  removeReservation(orderId: string): void
  addMovement(movement: StockMovement): void
  movements(): StockMovement[]
}

// The difference that a stock take found for one SKU: what the stock on hand
// was, what the count found, and the difference (below 0 when stock went
// missing).
export interface Variance {
  sku: string
  expected: number
  counted: number
  difference: number
}

// One movement with the stock on hand after it.
export interface BalanceLine {
  quantity: number
  reason: string
  balance: number
}

// The movements of one SKU with the running stock on hand, from 0.
export function runningBalance(movements: readonly StockMovement[]): BalanceLine[] {
  let balance = 0
  return movements.map((movement) => {
    balance += movement.quantity
    return { quantity: movement.quantity, reason: movement.reason, balance }
  })
}

export function emptyLevel(sku: string): StockLevel {
  return { sku, onHand: 0, reserved: 0 }
}

export function availableOf(level: StockLevel): number {
  return level.onHand - level.reserved
}

// The stock lines of an order, one for each SKU: the quantities of a SKU
// that is on several lines add up, in the order that each SKU first appears.
export function mergeLines(lines: readonly StockLine[]): StockLine[] {
  const merged: StockLine[] = []
  for (const line of lines) {
    const same = merged.find((m) => m.sku === line.sku)
    if (same === undefined) {
      merged.push({ ...line })
    } else {
      same.quantity += line.quantity
    }
  }
  return merged
}

export function checkLevel(level: StockLevel): void {
  check(level.reserved >= 0 && level.reserved <= level.onHand, `${level.sku} has a broken level`)
}

export function copyLevel(level: StockLevel): StockLevel {
  return { ...level }
}

export function copyReservation(reservation: Reservation): Reservation {
  return { orderId: reservation.orderId, lines: reservation.lines.map((line) => ({ ...line })) }
}
