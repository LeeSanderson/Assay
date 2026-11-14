import { describe, expect, it } from '@jest/globals'
import { Cart } from './cart.ts'
import { Catalogue, InMemoryProductRepository } from './catalogue.ts'
import { Checkout } from './checkout.ts'
import { FixedClock, SequentialIds } from './clock.ts'
import { InMemoryStockRepository, Inventory } from './inventory.ts'
import { InMemoryOrderRepository, Orders } from './orders.ts'
import { InMemoryPaymentGateway } from './payments.ts'
import type { Promotion } from './promotions.ts'
import { PromotionEngine } from './promotions.ts'
import type { CreditNote, ItemCondition, ReturnLine } from './returns.ts'
import { Returns } from './returns.ts'

const PLACED_ON = '2026-03-10'

// A shop with apples at 250 and pears at 1000, 20 of each in stock, and the
// promotions in its engine. The clock is on the date the orders are placed.
function shop(...promotions: Promotion[]) {
  const ids = new SequentialIds()
  const clock = new FixedClock(PLACED_ON)
  const catalogue = new Catalogue(new InMemoryProductRepository())
  catalogue.addProduct('apple', 'Apple', 250)
  catalogue.addProduct('pear', 'Pear', 1000)
  const inventory = new Inventory(new InMemoryStockRepository())
  inventory.receive('apple', 20)
  inventory.receive('pear', 20)
  const engine = new PromotionEngine()
  for (const promotion of promotions) engine.addPromotion(promotion)
  const repository = new InMemoryOrderRepository()
  const payments = new InMemoryPaymentGateway(ids)
  const checkout = new Checkout({
    catalogue,
    inventory,
    orders: repository,
    payments,
    clock,
    ids,
    promotions: engine,
  })
  const orders = new Orders(repository, inventory, payments)
  const returns = new Returns({ orders: repository, inventory, payments, clock, ids })
  // place(['apple', 2], ...) places an order of those lines.
  const place = (...items: [string, number][]) => {
    const cart = new Cart()
    for (const [sku, quantity] of items) cart.add(sku, quantity)
    return checkout.placeOrder({ cart, paymentToken: 'card' })
  }
  // shipped(...) places an order of those lines and ships it.
  const shipped = (...items: [string, number][]) => {
    const order = place(...items)
    orders.ship(order.id)
    return order
  }
  return { clock, engine, inventory, payments, checkout, orders, returns, place, shipped }
}

function resellable(sku: string, quantity: number): ReturnLine {
  return { sku, quantity, condition: 'resellable' }
}

function damaged(sku: string, quantity: number): ReturnLine {
  return { sku, quantity, condition: 'damaged' }
}

// The credit note without its id, which the tests do not fix.
function withoutId(note: CreditNote): Omit<CreditNote, 'id'> {
  const { id, ...rest } = note
  expect(typeof id).toBe('string')
  return rest
}

const tenPercent: Promotion = { id: 'ten', kind: 'percentage', percent: 10 }

describe('returns', () => {
  it('returns part of a shipped order and issues a credit note', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 4])
    const note = returns.returnItems(order.id, [resellable('apple', 1)])
    expect(withoutId(note)).toEqual({
      orderId: order.id,
      lines: [{ sku: 'apple', quantity: 1, amount: 250 }],
      discounts: [],
      amount: 250,
      issuedOn: PLACED_ON,
    })
  })

  it('returns several lines in one credit note, in the order of the return', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 4], ['pear', 2])
    const note = returns.returnItems(order.id, [resellable('pear', 1), resellable('apple', 2)])
    expect(note.lines).toEqual([
      { sku: 'pear', quantity: 1, amount: 1000 },
      { sku: 'apple', quantity: 2, amount: 500 },
    ])
    expect(note.amount).toBe(1500)
  })

  it('issues the credit note on the date of the clock', () => {
    const { clock, returns, shipped } = shop()
    const order = shipped(['apple', 4])
    clock.set('2026-03-25')
    expect(returns.returnItems(order.id, [resellable('apple', 1)]).issuedOn).toBe('2026-03-25')
  })

  it('gives each credit note its own id and lists the credit notes of an order', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 4])
    const first = returns.returnItems(order.id, [resellable('apple', 1)])
    const second = returns.returnItems(order.id, [resellable('apple', 2)])
    expect(first.id).not.toBe(second.id)
    expect(returns.creditNotes(order.id)).toEqual([first, second])
  })

  it('lists no credit notes for an order with no return', () => {
    const { returns, shipped } = shop()
    expect(returns.creditNotes(shipped(['apple', 1]).id)).toEqual([])
  })

  it('keeps the lines and the totals of the order as placed', () => {
    const { orders, returns, shipped } = shop(tenPercent)
    const order = shipped(['apple', 4], ['pear', 1])
    returns.returnItems(order.id, [resellable('apple', 1)])
    const after = orders.order(order.id)
    expect(after.lines.map((line) => [line.sku, line.unitPrice, line.quantity])).toEqual([
      ['apple', 250, 4],
      ['pear', 1000, 1],
    ])
    expect([after.subtotal, after.discounts, after.total]).toEqual([
      2000,
      [{ promotionId: 'ten', amount: 200 }],
      1800,
    ])
  })
})

describe('restock', () => {
  it('puts resellable units back into the stock on hand', () => {
    const { inventory, returns, shipped } = shop()
    const order = shipped(['apple', 4])
    returns.returnItems(order.id, [resellable('apple', 3)])
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 19, reserved: 0 })
    const movements = inventory.movements('apple')
    expect(movements[movements.length - 1]).toEqual({
      sku: 'apple',
      quantity: 3,
      reason: 'returned',
    })
  })

  it('does not put damaged units back into stock', () => {
    const { inventory, returns, shipped } = shop()
    const order = shipped(['apple', 4])
    const before = inventory.movements('apple')
    const note = returns.returnItems(order.id, [damaged('apple', 3)])
    expect(note.amount).toBe(750)
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 16, reserved: 0 })
    expect(inventory.movements('apple')).toEqual(before)
  })

  it('restocks each line of a return by its condition', () => {
    const { inventory, returns, shipped } = shop()
    const order = shipped(['apple', 4], ['pear', 2])
    returns.returnItems(order.id, [damaged('apple', 1), resellable('pear', 2)])
    expect(inventory.available('apple')).toBe(16)
    expect(inventory.available('pear')).toBe(20)
  })
})

describe('refunds with discounts', () => {
  it('reverses a percentage discount in proportion to the units returned', () => {
    const { returns, shipped } = shop(tenPercent)
    const order = shipped(['apple', 4])
    const note = returns.returnItems(order.id, [resellable('apple', 1)])
    expect(note.lines).toEqual([{ sku: 'apple', quantity: 1, amount: 225 }])
    expect(note.discounts).toEqual([{ promotionId: 'ten', amount: 25 }])
    expect(note.amount).toBe(225)
  })

  it('rounds each reversal down and reverses the whole discount once every unit is back', () => {
    const { returns, shipped } = shop({ id: 'fifteen', kind: 'percentage', percent: 15 })
    const order = shipped(['apple', 3]) // 750, less a discount of 112
    const amounts = [1, 1, 1].map(
      (quantity) => returns.returnItems(order.id, [resellable('apple', quantity)]).amount
    )
    expect(amounts).toEqual([213, 213, 212])
    expect(returns.creditNotes(order.id).map((note) => note.discounts)).toEqual([
      [{ promotionId: 'fifteen', amount: 37 }],
      [{ promotionId: 'fifteen', amount: 37 }],
      [{ promotionId: 'fifteen', amount: 38 }],
    ])
  })

  it('reverses only the discounts that took from the returned line', () => {
    const { returns, shipped } = shop({
      id: 'apples',
      kind: 'percentage',
      percent: 10,
      skus: ['apple'],
    })
    const order = shipped(['apple', 2], ['pear', 1])
    const note = returns.returnItems(order.id, [resellable('pear', 1)])
    expect(note.amount).toBe(1000)
    expect(note.discounts).toEqual([])
  })

  it('reverses a fixed discount on the lines that it took from', () => {
    // 300 off: 250 from the apple line, then 50 from the pear line.
    const { returns, shipped } = shop({ id: 'off', kind: 'fixed', amount: 300 })
    const order = shipped(['apple', 1], ['pear', 1])
    const note = returns.returnItems(order.id, [resellable('pear', 1)])
    expect(note.lines).toEqual([{ sku: 'pear', quantity: 1, amount: 950 }])
    expect(note.discounts).toEqual([{ promotionId: 'off', amount: 50 }])
  })

  it('reverses a buy-x-get-y discount in proportion to the units returned', () => {
    const { returns, shipped } = shop({ id: 'three-for-two', kind: 'buy-x-get-y', buy: 2, get: 1 })
    const order = shipped(['apple', 3]) // 750, less one free apple
    const note = returns.returnItems(order.id, [resellable('apple', 1)])
    expect(note.amount).toBe(167)
    expect(note.discounts).toEqual([{ promotionId: 'three-for-two', amount: 83 }])
  })

  it('gives a bundle that is returned in part a new price', () => {
    // Two sets of an apple and a pear at 900: a saving of 700, 500 from the
    // apple line and 200 from the pear line.
    const { orders, returns, shipped } = shop({
      id: 'pair',
      kind: 'bundle',
      skus: ['apple', 'pear'],
      price: 900,
    })
    const order = shipped(['apple', 2], ['pear', 2])
    expect(order.total).toBe(1800)
    const note = returns.returnItems(order.id, [resellable('pear', 1)])
    expect(note.lines).toEqual([{ sku: 'pear', quantity: 1, amount: 900 }])
    expect(note.discounts).toEqual([{ promotionId: 'pair', amount: 100 }])
    expect(orders.revenue()).toBe(900)
  })

  it('reverses each discount on a line on its own, in the order of the discounts', () => {
    const { returns, shipped } = shop(
      { id: 'ten', kind: 'percentage', percent: 10, priority: 1 },
      { id: 'off', kind: 'fixed', amount: 100 }
    )
    const order = shipped(['apple', 4]) // 1000, less 100 and then 100
    const note = returns.returnItems(order.id, [resellable('apple', 1)])
    expect(note.discounts).toEqual([
      { promotionId: 'ten', amount: 25 },
      { promotionId: 'off', amount: 25 },
    ])
    expect(note.amount).toBe(200)
  })

  it('adds up the reversals of a discount over the lines of a return', () => {
    const { returns, shipped } = shop(tenPercent)
    const order = shipped(['apple', 2], ['pear', 1])
    const note = returns.returnItems(order.id, [resellable('apple', 1), resellable('pear', 1)])
    expect(note.lines).toEqual([
      { sku: 'apple', quantity: 1, amount: 225 },
      { sku: 'pear', quantity: 1, amount: 900 },
    ])
    expect(note.discounts).toEqual([{ promotionId: 'ten', amount: 125 }])
    expect(note.amount).toBe(1125)
  })

  it('reverses the discount of a coupon', () => {
    const { checkout, engine, orders, returns } = shop()
    engine.addCoupon({
      code: 'SAVE20',
      promotion: { id: 'save-twenty', kind: 'percentage', percent: 20 },
      expiresOn: '2026-12-31',
      usageLimit: 1,
    })
    const cart = new Cart()
    cart.add('apple', 2)
    const order = checkout.placeOrder({ cart, paymentToken: 'card', coupons: ['SAVE20'] })
    orders.ship(order.id)
    const note = returns.returnItems(order.id, [resellable('apple', 1)])
    expect(note.amount).toBe(200)
    expect(note.discounts).toEqual([{ promotionId: 'save-twenty', amount: 50 }])
  })
})

describe('payments', () => {
  it('refunds the amount of each credit note to the payment of the order', () => {
    const { payments, returns, shipped } = shop(tenPercent)
    const order = shipped(['apple', 4])
    returns.returnItems(order.id, [resellable('apple', 1)])
    returns.returnItems(order.id, [damaged('apple', 2)])
    expect(payments.refunds()).toEqual([
      { paymentId: order.paymentId, amount: 225 },
      { paymentId: order.paymentId, amount: 450 },
    ])
  })

  it('refunds the whole payment once every unit is back', () => {
    const { payments, returns, shipped } = shop({ id: 'fifteen', kind: 'percentage', percent: 15 })
    const order = shipped(['apple', 3], ['pear', 1])
    returns.returnItems(order.id, [resellable('apple', 2)])
    returns.returnItems(order.id, [resellable('apple', 1), resellable('pear', 1)])
    const refunded = payments.refunds().reduce((sum, refund) => sum + refund.amount, 0)
    expect(refunded).toBe(order.total)
  })

  it('refunds nothing for units that cost nothing', () => {
    // 250 off takes the whole price of the apple line.
    const { payments, returns, shipped } = shop({ id: 'off', kind: 'fixed', amount: 250 })
    const order = shipped(['apple', 1], ['pear', 1])
    const note = returns.returnItems(order.id, [resellable('apple', 1)])
    expect(note.lines).toEqual([{ sku: 'apple', quantity: 1, amount: 0 }])
    expect(note.discounts).toEqual([{ promotionId: 'off', amount: 250 }])
    expect(note.amount).toBe(0)
    expect(payments.refunds()).toEqual([])
  })
})

describe('orders', () => {
  it('keeps an order shipped while it has units left to return', () => {
    const { orders, returns, shipped } = shop()
    const order = shipped(['apple', 2], ['pear', 1])
    returns.returnItems(order.id, [resellable('apple', 2)])
    expect(orders.order(order.id).status).toBe('shipped')
  })

  it('marks an order returned once every unit is back', () => {
    const { orders, returns, shipped } = shop()
    const order = shipped(['apple', 2], ['pear', 1])
    returns.returnItems(order.id, [resellable('apple', 1)])
    returns.returnItems(order.id, [resellable('pear', 1), damaged('apple', 1)])
    expect(orders.order(order.id).status).toBe('returned')
    expect(orders.withStatus('returned').map((o) => o.id)).toEqual([order.id])
    expect(orders.withStatus('shipped')).toEqual([])
  })

  it('rejects a change to a returned order', () => {
    const { orders, returns, shipped } = shop()
    const order = shipped(['apple', 1])
    returns.returnItems(order.id, [resellable('apple', 1)])
    expect(() => orders.ship(order.id)).toThrow(`order ${order.id} is returned`)
    expect(() => orders.cancel(order.id)).toThrow(`order ${order.id} is returned`)
    expect(() => returns.returnItems(order.id, [resellable('apple', 1)])).toThrow(
      `order ${order.id} is returned`
    )
  })

  it('takes the credit notes off the revenue', () => {
    const { orders, returns, place, shipped } = shop(tenPercent)
    place(['pear', 1]) // 900
    const order = shipped(['apple', 4]) // 900
    returns.returnItems(order.id, [resellable('apple', 1)])
    expect(orders.revenue()).toBe(1575)
  })

  it('counts the units returned out of the best sellers', () => {
    const { orders, returns, shipped } = shop()
    const first = shipped(['apple', 3], ['pear', 2])
    const second = shipped(['pear', 1])
    returns.returnItems(first.id, [resellable('apple', 2)])
    returns.returnItems(second.id, [resellable('pear', 1)])
    expect(orders.bestSellers(5)).toEqual([
      { sku: 'pear', quantity: 2 },
      { sku: 'apple', quantity: 1 },
    ])
    returns.returnItems(first.id, [resellable('apple', 1)])
    expect(orders.bestSellers(5)).toEqual([{ sku: 'pear', quantity: 2 }])
  })
})

describe('the return window', () => {
  it('accepts a return up to and including 30 days after the order was placed', () => {
    const { clock, returns, shipped } = shop()
    const order = shipped(['apple', 2])
    clock.set('2026-04-09')
    expect(returns.returnItems(order.id, [resellable('apple', 1)]).amount).toBe(250)
  })

  it('rejects a return after the return window', () => {
    const { clock, returns, shipped } = shop()
    const order = shipped(['apple', 2])
    clock.set('2026-04-10')
    expect(() => returns.returnItems(order.id, [resellable('apple', 1)])).toThrow(
      `the return window of order ${order.id} has closed`
    )
  })
})

describe('errors', () => {
  it('rejects a return of an unknown order', () => {
    const { returns } = shop()
    expect(() => returns.returnItems('no-such-order', [resellable('apple', 1)])).toThrow(
      'unknown order no-such-order'
    )
    expect(() => returns.creditNotes('no-such-order')).toThrow('unknown order no-such-order')
  })

  it('rejects a return of an order that has not shipped', () => {
    const { returns, place } = shop()
    const order = place(['apple', 2])
    expect(() => returns.returnItems(order.id, [resellable('apple', 1)])).toThrow(
      `order ${order.id} is paid`
    )
  })

  it('rejects a return of a cancelled order', () => {
    const { orders, returns, place } = shop()
    const order = place(['apple', 2])
    orders.cancel(order.id)
    expect(() => returns.returnItems(order.id, [resellable('apple', 1)])).toThrow(
      `order ${order.id} is cancelled`
    )
  })

  it('rejects a return with no lines', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 2])
    expect(() => returns.returnItems(order.id, [])).toThrow('nothing to return')
  })

  it('rejects a SKU that is not in the order', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 2])
    expect(() => returns.returnItems(order.id, [resellable('pear', 1)])).toThrow(
      `SKU pear is not in order ${order.id}`
    )
  })

  it('rejects a quantity below 1', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 2])
    expect(() => returns.returnItems(order.id, [resellable('apple', 0)])).toThrow(
      'quantity must be at least 1'
    )
  })

  it('rejects more units than are left to return', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 3])
    returns.returnItems(order.id, [resellable('apple', 2)])
    expect(() => returns.returnItems(order.id, [resellable('apple', 2)])).toThrow(
      'apple has 1 left to return'
    )
  })

  it('rejects a SKU in more than one line', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 3])
    expect(() =>
      returns.returnItems(order.id, [resellable('apple', 1), damaged('apple', 1)])
    ).toThrow('SKU apple is in more than one line')
  })

  it('rejects an unknown condition', () => {
    const { returns, shipped } = shop()
    const order = shipped(['apple', 3])
    const condition = 'broken' as string as ItemCondition
    expect(() => returns.returnItems(order.id, [{ sku: 'apple', quantity: 1, condition }])).toThrow(
      'unknown condition broken'
    )
  })

  it('changes nothing when a return fails', () => {
    const { inventory, orders, payments, returns, shipped } = shop()
    const order = shipped(['apple', 3], ['pear', 1])
    expect(() =>
      returns.returnItems(order.id, [resellable('apple', 1), resellable('pear', 2)])
    ).toThrow('pear has 1 left to return')
    expect(inventory.available('apple')).toBe(17)
    expect(payments.refunds()).toEqual([])
    expect(returns.creditNotes(order.id)).toEqual([])
    expect(orders.order(order.id).status).toBe('shipped')
    expect(returns.returnItems(order.id, [resellable('apple', 3)]).amount).toBe(750)
  })
})
