import { describe, expect, it } from '@jest/globals'
import {
  checkPurchaseLine,
  checkPurchaseStatus,
  checkSupplier,
  costOfPurchase,
  isReceived,
  outstanding,
} from './purchase.ts'
import type { PurchaseOrder } from './purchase.ts'

const ORDER: PurchaseOrder = {
  id: 'purchase-1',
  supplierId: 'supplier-1',
  lines: [
    { sku: 'apple', quantity: 10, unitCost: 120, received: 10 },
    { sku: 'pear', quantity: 4, unitCost: 600, received: 1 },
  ],
  status: 'sent',
  createdOn: '2026-03-10',
}

describe('purchase orders', () => {
  it('knows what is outstanding and what the order costs', () => {
    expect(ORDER.lines.map(outstanding)).toEqual([0, 3])
    expect(isReceived(ORDER)).toBe(false)
    expect(costOfPurchase(ORDER)).toBe(3600)
  })

  it('is received once every unit has come in', () => {
    const lines = ORDER.lines.map((line) => ({ ...line, received: line.quantity }))
    expect(isReceived({ ...ORDER, lines })).toBe(true)
  })

  it('checks its status', () => {
    expect(() => checkPurchaseStatus(ORDER, 'draft')).toThrow('purchase purchase-1 is sent')
  })

  it('checks a supplier and a line', () => {
    expect(() => checkSupplier('Orchard', 'sales@orchard.example', -1)).toThrow(
      'lead time must be a whole number of days'
    )
    expect(() => checkPurchaseLine('apple', 1, 0)).toThrow('unit cost must be at least 1')
    expect(() => checkPurchaseLine('apple', 0, 10)).toThrow('quantity must be at least 1')
  })
})
