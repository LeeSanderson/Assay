import { describe, expect, it } from '@jest/globals'
import {
  type Coupon,
  type Line,
  type Promotion,
  type PromotionKind,
  PromotionEngine,
} from './promotions.ts'
import { Cart } from './cart.ts'
import { Catalogue, InMemoryProductRepository } from './catalogue.ts'
import { Checkout } from './checkout.ts'
import { FixedClock, SequentialIds } from './clock.ts'
import { InMemoryStockRepository, Inventory } from './inventory.ts'
import { InMemoryOrderRepository, Orders } from './orders.ts'
import { InMemoryPaymentGateway } from './payments.ts'

const TODAY = '2026-03-10'

// The cart that most cases price: a subtotal of 1500.
const CART: Line[] = [
  { sku: 'apple', unitPrice: 250, quantity: 2 },
  { sku: 'pear', unitPrice: 1000, quantity: 1 },
]

function engineWith(...promotions: Promotion[]): PromotionEngine {
  const engine = new PromotionEngine()
  for (const promotion of promotions) engine.addPromotion(promotion)
  return engine
}

function saveTen(usageLimit = 5, promotion: Partial<Promotion> = {}): Coupon {
  return {
    code: 'SAVE10',
    promotion: { id: 'save-ten', kind: 'percentage', percent: 10, ...promotion },
    expiresOn: '2026-03-31',
    usageLimit,
  }
}

// The message of the error that the action throws.
function thrown(action: () => unknown): string {
  try {
    action()
  } catch (error) {
    return (error as Error).message
  }
  return 'nothing was thrown'
}

describe('the cart', () => {
  it('prices a cart with no promotions at its subtotal', () => {
    expect(new PromotionEngine().quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [],
      total: 1500,
    })
  })

  it('prices an empty cart at zero', () => {
    expect(new PromotionEngine().quote([], [], TODAY)).toEqual({
      subtotal: 0,
      discounts: [],
      total: 0,
    })
  })

  it('rejects a line with a quantity below 1', () => {
    const lines = [{ sku: 'apple', unitPrice: 100, quantity: 0 }]
    expect(thrown(() => new PromotionEngine().quote(lines, [], TODAY))).toBe(
      'quantity must be at least 1'
    )
  })

  it('rejects two lines with the same SKU', () => {
    const lines = [
      { sku: 'apple', unitPrice: 100, quantity: 1 },
      { sku: 'apple', unitPrice: 100, quantity: 2 },
    ]
    expect(thrown(() => new PromotionEngine().quote(lines, [], TODAY))).toBe(
      'SKU apple is in more than one line'
    )
  })
})

describe('percentage discounts', () => {
  it('takes the percentage off every line when the promotion names no SKUs', () => {
    const engine = engineWith({ id: 'ten', kind: 'percentage', percent: 10 })
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'ten', amount: 150 }],
      total: 1350,
    })
  })

  it('takes the percentage off the named SKUs only', () => {
    const engine = engineWith({ id: 'ten', kind: 'percentage', percent: 10, skus: ['pear'] })
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'ten', amount: 100 }],
      total: 1400,
    })
  })

  it('rounds the discount down to a whole cent on each line', () => {
    const engine = engineWith({ id: 'fifteen', kind: 'percentage', percent: 15 })
    const lines = [
      { sku: 'apple', unitPrice: 333, quantity: 1 },
      { sku: 'pear', unitPrice: 333, quantity: 1 },
    ]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 666,
      discounts: [{ promotionId: 'fifteen', amount: 98 }],
      total: 568,
    })
  })

  it('rejects a percent outside 1 to 100', () => {
    const engine = new PromotionEngine()
    for (const percent of [0, 101]) {
      expect(thrown(() => engine.addPromotion({ id: 'p', kind: 'percentage', percent }))).toBe(
        'percent must be between 1 and 100'
      )
    }
  })
})

describe('fixed discounts', () => {
  it('takes the amount off the cart', () => {
    const engine = engineWith({ id: 'off', kind: 'fixed', amount: 300 })
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 300 }],
      total: 1200,
    })
  })

  it('takes the amount off the named SKUs only, up to what they cost', () => {
    const engine = engineWith({ id: 'off', kind: 'fixed', amount: 600, skus: ['apple'] })
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 500 }],
      total: 1000,
    })
  })

  it('never takes the cart below zero', () => {
    const engine = engineWith({ id: 'off', kind: 'fixed', amount: 5000 })
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 1500 }],
      total: 0,
    })
  })

  it('rejects an amount that is not positive', () => {
    const engine = new PromotionEngine()
    expect(thrown(() => engine.addPromotion({ id: 'off', kind: 'fixed', amount: 0 }))).toBe(
      'amount must be positive'
    )
  })
})

describe('buy X get Y', () => {
  it('makes Y units free for each full group of X plus Y units', () => {
    const engine = engineWith({
      id: 'three-for-two',
      kind: 'buy-x-get-y',
      buy: 2,
      get: 1,
      skus: ['apple'],
    })
    const lines = [{ sku: 'apple', unitPrice: 100, quantity: 7 }]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 700,
      discounts: [{ promotionId: 'three-for-two', amount: 200 }],
      total: 500,
    })
  })

  it('gives nothing for an incomplete group', () => {
    const engine = engineWith({ id: 'three-for-two', kind: 'buy-x-get-y', buy: 2, get: 1 })
    const lines = [{ sku: 'apple', unitPrice: 100, quantity: 2 }]
    expect(engine.quote(lines, [], TODAY)).toEqual({ subtotal: 200, discounts: [], total: 200 })
  })

  it('counts the units of each line on its own', () => {
    const engine = engineWith({ id: 'two-for-one', kind: 'buy-x-get-y', buy: 1, get: 1 })
    const lines = [
      { sku: 'apple', unitPrice: 100, quantity: 3 },
      { sku: 'pear', unitPrice: 50, quantity: 1 },
    ]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 350,
      discounts: [{ promotionId: 'two-for-one', amount: 100 }],
      total: 250,
    })
  })

  it('rejects buy or get below 1', () => {
    const engine = new PromotionEngine()
    for (const [buy, get] of [
      [0, 1],
      [1, 0],
    ]) {
      expect(thrown(() => engine.addPromotion({ id: 'b', kind: 'buy-x-get-y', buy, get }))).toBe(
        'buy and get must be at least 1'
      )
    }
  })
})

describe('bundles', () => {
  const meal = (price: number): Promotion => ({
    id: 'meal',
    kind: 'bundle',
    skus: ['burger', 'fries', 'drink'],
    price,
  })

  it('prices each complete set of the SKUs at the bundle price', () => {
    const lines = [
      { sku: 'burger', unitPrice: 500, quantity: 2 },
      { sku: 'fries', unitPrice: 200, quantity: 2 },
      { sku: 'drink', unitPrice: 150, quantity: 1 },
    ]
    expect(engineWith(meal(700)).quote(lines, [], TODAY)).toEqual({
      subtotal: 1550,
      discounts: [{ promotionId: 'meal', amount: 150 }],
      total: 1400,
    })
  })

  it('gives nothing when a SKU of the bundle is not in the cart', () => {
    const lines = [
      { sku: 'burger', unitPrice: 500, quantity: 1 },
      { sku: 'fries', unitPrice: 200, quantity: 1 },
    ]
    expect(engineWith(meal(100)).quote(lines, [], TODAY)).toEqual({
      subtotal: 700,
      discounts: [],
      total: 700,
    })
  })

  it('gives nothing when the bundle price is not below the price of its SKUs', () => {
    const lines = [
      { sku: 'burger', unitPrice: 500, quantity: 1 },
      { sku: 'fries', unitPrice: 200, quantity: 1 },
      { sku: 'drink', unitPrice: 150, quantity: 1 },
    ]
    expect(engineWith(meal(850)).quote(lines, [], TODAY)).toEqual({
      subtotal: 850,
      discounts: [],
      total: 850,
    })
  })

  it('rejects a bundle with fewer than two SKUs', () => {
    const engine = new PromotionEngine()
    const bundle: Promotion = { id: 'meal', kind: 'bundle', skus: ['burger'], price: 100 }
    expect(thrown(() => engine.addPromotion(bundle))).toBe('a bundle needs at least two SKUs')
  })

  it('rejects a negative bundle price', () => {
    const engine = new PromotionEngine()
    const bundle: Promotion = { id: 'meal', kind: 'bundle', skus: ['burger', 'fries'], price: -1 }
    expect(thrown(() => engine.addPromotion(bundle))).toBe('bundle price must not be negative')
  })
})

describe('precedence', () => {
  it('applies promotions from the highest priority down', () => {
    const engine = engineWith(
      { id: 'a-percent', kind: 'percentage', percent: 10, priority: 1 },
      { id: 'b-fixed', kind: 'fixed', amount: 100, priority: 2 }
    )
    const lines = [{ sku: 'apple', unitPrice: 1000, quantity: 1 }]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 1000,
      discounts: [
        { promotionId: 'b-fixed', amount: 100 },
        { promotionId: 'a-percent', amount: 90 },
      ],
      total: 810,
    })
  })

  it('breaks a priority tie by promotion id', () => {
    const engine = engineWith(
      { id: 'z-percent', kind: 'percentage', percent: 10 },
      { id: 'a-fixed', kind: 'fixed', amount: 100 }
    )
    const lines = [{ sku: 'apple', unitPrice: 1000, quantity: 1 }]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 1000,
      discounts: [
        { promotionId: 'a-fixed', amount: 100 },
        { promotionId: 'z-percent', amount: 90 },
      ],
      total: 810,
    })
  })

  it('takes a fixed discount from the lines in cart order', () => {
    const engine = engineWith(
      { id: 'off', kind: 'fixed', amount: 300, priority: 2 },
      { id: 'half-pear', kind: 'percentage', percent: 50, skus: ['pear'], priority: 1 }
    )
    const lines = [
      { sku: 'apple', unitPrice: 200, quantity: 1 },
      { sku: 'pear', unitPrice: 500, quantity: 1 },
    ]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 700,
      discounts: [
        { promotionId: 'off', amount: 300 },
        { promotionId: 'half-pear', amount: 200 },
      ],
      total: 200,
    })
  })

  it('lets a later promotion work on what earlier promotions left', () => {
    const engine = engineWith(
      { id: 'three-for-two', kind: 'buy-x-get-y', buy: 2, get: 1, priority: 2 },
      { id: 'ten', kind: 'percentage', percent: 10, priority: 1 }
    )
    const lines = [{ sku: 'apple', unitPrice: 100, quantity: 3 }]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 300,
      discounts: [
        { promotionId: 'three-for-two', amount: 100 },
        { promotionId: 'ten', amount: 20 },
      ],
      total: 180,
    })
  })

  it('limits a buy X get Y discount to what is left of the line', () => {
    const engine = engineWith(
      { id: 'sixty', kind: 'percentage', percent: 60, priority: 2 },
      { id: 'two-for-one', kind: 'buy-x-get-y', buy: 1, get: 1, priority: 1 }
    )
    const lines = [{ sku: 'apple', unitPrice: 100, quantity: 2 }]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 200,
      discounts: [
        { promotionId: 'sixty', amount: 120 },
        { promotionId: 'two-for-one', amount: 80 },
      ],
      total: 0,
    })
  })

  it('takes a bundle saving from its lines in cart order', () => {
    const engine = engineWith(
      { id: 'meal', kind: 'bundle', skus: ['burger', 'fries', 'drink'], price: 100, priority: 2 },
      { id: 'half-fries', kind: 'percentage', percent: 50, skus: ['fries'], priority: 1 }
    )
    const lines = [
      { sku: 'drink', unitPrice: 150, quantity: 1 },
      { sku: 'burger', unitPrice: 500, quantity: 1 },
      { sku: 'fries', unitPrice: 200, quantity: 1 },
    ]
    expect(engine.quote(lines, [], TODAY)).toEqual({
      subtotal: 850,
      discounts: [
        { promotionId: 'meal', amount: 750 },
        { promotionId: 'half-fries', amount: 50 },
      ],
      total: 50,
    })
  })
})

describe('stacking and exclusivity', () => {
  it('stacks every promotion that applies', () => {
    const engine = engineWith(
      { id: 'ten', kind: 'percentage', percent: 10 },
      { id: 'off-fifty', kind: 'fixed', amount: 50 }
    )
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [
        { promotionId: 'off-fifty', amount: 50 },
        { promotionId: 'ten', amount: 145 },
      ],
      total: 1305,
    })
  })

  it('leaves out a promotion that takes nothing off', () => {
    const engine = engineWith(
      { id: 'plum-ten', kind: 'percentage', percent: 10, skus: ['plum'] },
      { id: 'off', kind: 'fixed', amount: 100 }
    )
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 100 }],
      total: 1400,
    })
  })

  it('applies an exclusive promotion alone when it comes first', () => {
    const engine = engineWith(
      { id: 'vip', kind: 'percentage', percent: 20, exclusive: true, priority: 5 },
      { id: 'off', kind: 'fixed', amount: 100, priority: 1 }
    )
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'vip', amount: 300 }],
      total: 1200,
    })
  })

  it('skips an exclusive promotion when an earlier promotion applied', () => {
    const engine = engineWith(
      { id: 'off', kind: 'fixed', amount: 100, priority: 5 },
      { id: 'vip', kind: 'percentage', percent: 20, exclusive: true, priority: 1 }
    )
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 100 }],
      total: 1400,
    })
  })

  it('considers the next promotion when an exclusive promotion takes nothing off', () => {
    const engine = engineWith(
      {
        id: 'plum-deal',
        kind: 'buy-x-get-y',
        buy: 1,
        get: 1,
        skus: ['plum'],
        exclusive: true,
        priority: 5,
      },
      { id: 'off', kind: 'fixed', amount: 100, priority: 1 }
    )
    expect(engine.quote(CART, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 100 }],
      total: 1400,
    })
  })

  it('rejects a promotion id that is already in the engine', () => {
    const engine = engineWith({ id: 'ten', kind: 'percentage', percent: 10 })
    expect(thrown(() => engine.addPromotion({ id: 'ten', kind: 'fixed', amount: 100 }))).toBe(
      'promotion ten already exists'
    )
  })

  it('rejects an unknown promotion kind', () => {
    const engine = new PromotionEngine()
    const gift = { id: 'gift', kind: 'gift' as PromotionKind, amount: 100 }
    expect(thrown(() => engine.addPromotion(gift))).toBe('unknown promotion kind gift')
  })
})

describe('coupons', () => {
  function engineWithCoupon(coupon: Coupon, ...promotions: Promotion[]): PromotionEngine {
    const engine = engineWith(...promotions)
    engine.addCoupon(coupon)
    return engine
  }

  it('applies the promotion of a coupon only when its code is given', () => {
    const engine = engineWithCoupon(saveTen())
    expect(engine.quote(CART, [], TODAY)).toEqual({ subtotal: 1500, discounts: [], total: 1500 })
    expect(engine.quote(CART, ['SAVE10'], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'save-ten', amount: 150 }],
      total: 1350,
    })
  })

  it('orders a coupon promotion with the other promotions', () => {
    const engine = engineWithCoupon(
      saveTen(5, { priority: 2 }),
      { id: 'first', kind: 'fixed', amount: 100, priority: 3 },
      { id: 'last', kind: 'fixed', amount: 50, priority: 1 }
    )
    const lines = [{ sku: 'apple', unitPrice: 1000, quantity: 1 }]
    expect(engine.quote(lines, ['SAVE10'], TODAY)).toEqual({
      subtotal: 1000,
      discounts: [
        { promotionId: 'first', amount: 100 },
        { promotionId: 'save-ten', amount: 90 },
        { promotionId: 'last', amount: 50 },
      ],
      total: 760,
    })
  })

  it('accepts a coupon on its expiry date', () => {
    const engine = engineWithCoupon(saveTen())
    expect(engine.quote(CART, ['SAVE10'], '2026-03-31').total).toBe(1350)
  })

  it('rejects a coupon after its expiry date', () => {
    const engine = engineWithCoupon(saveTen())
    expect(thrown(() => engine.quote(CART, ['SAVE10'], '2026-04-01'))).toBe(
      'coupon SAVE10 has expired'
    )
  })

  it('rejects an unknown coupon code', () => {
    const engine = engineWithCoupon(saveTen())
    expect(thrown(() => engine.quote(CART, ['NOPE'], TODAY))).toBe('unknown coupon NOPE')
  })

  it('rejects a code given twice in one cart', () => {
    const engine = engineWithCoupon(saveTen())
    expect(thrown(() => engine.quote(CART, ['SAVE10', 'SAVE10'], TODAY))).toBe(
      'coupon SAVE10 given more than once'
    )
  })

  it('does not use a coupon when quoting', () => {
    const engine = engineWithCoupon(saveTen(1))
    const quote = engine.quote(CART, ['SAVE10'], TODAY)
    expect(engine.quote(CART, ['SAVE10'], TODAY)).toEqual(quote)
    expect(engine.redeem(CART, ['SAVE10'], TODAY)).toEqual(quote)
  })

  it('uses each coupon once on each redeem until its usage limit', () => {
    const engine = engineWithCoupon(saveTen(2))
    expect(engine.redeem(CART, ['SAVE10'], TODAY).total).toBe(1350)
    expect(engine.redeem(CART, ['SAVE10'], TODAY).total).toBe(1350)
    expect(thrown(() => engine.redeem(CART, ['SAVE10'], TODAY))).toBe(
      'coupon SAVE10 has reached its usage limit'
    )
    expect(thrown(() => engine.quote(CART, ['SAVE10'], TODAY))).toBe(
      'coupon SAVE10 has reached its usage limit'
    )
  })

  it('counts a use even when the coupon promotion takes nothing off', () => {
    const engine = engineWithCoupon(saveTen(1, { skus: ['plum'] }))
    expect(engine.redeem(CART, ['SAVE10'], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [],
      total: 1500,
    })
    expect(thrown(() => engine.redeem(CART, ['SAVE10'], TODAY))).toBe(
      'coupon SAVE10 has reached its usage limit'
    )
  })

  it('uses no coupon when a redeem fails', () => {
    const engine = engineWithCoupon(saveTen(1))
    expect(thrown(() => engine.redeem(CART, ['SAVE10', 'NOPE'], TODAY))).toBe(
      'unknown coupon NOPE'
    )
    expect(engine.redeem(CART, ['SAVE10'], TODAY).total).toBe(1350)
  })

  it('rejects a coupon code that is already in the engine', () => {
    const engine = engineWithCoupon(saveTen())
    const again = { ...saveTen(), promotion: { id: 'other', kind: 'fixed' as const, amount: 1 } }
    expect(thrown(() => engine.addCoupon(again))).toBe('coupon SAVE10 already exists')
  })

  it('rejects a coupon usage limit below 1', () => {
    const engine = new PromotionEngine()
    expect(thrown(() => engine.addCoupon(saveTen(0)))).toBe('usage limit must be at least 1')
  })

  it('rejects a coupon whose promotion id is already in the engine', () => {
    const engine = engineWith({ id: 'save-ten', kind: 'fixed', amount: 100 })
    expect(thrown(() => engine.addCoupon(saveTen()))).toBe('promotion save-ten already exists')
  })

  it('rejects a coupon whose promotion is not valid', () => {
    const engine = new PromotionEngine()
    expect(thrown(() => engine.addCoupon(saveTen(5, { percent: 0 })))).toBe(
      'percent must be between 1 and 100'
    )
  })
})

// --- The checkout ------------------------------------------------------------

// A shop with apples at 250 (10 in stock) and pears at 1000 (5 in stock),
// whose checkout prices carts with the engine.
function shopWith(engine: PromotionEngine) {
  const ids = new SequentialIds()
  const clock = new FixedClock(TODAY)
  const catalogue = new Catalogue(new InMemoryProductRepository())
  catalogue.addProduct('apple', 'Apple', 250)
  catalogue.addProduct('pear', 'Pear', 1000)
  const inventory = new Inventory(new InMemoryStockRepository())
  inventory.receive('apple', 10)
  inventory.receive('pear', 5)
  const orders = new InMemoryOrderRepository()
  const payments = new InMemoryPaymentGateway(ids)
  const checkout = new Checkout({
    catalogue,
    inventory,
    orders,
    payments,
    clock,
    ids,
    promotions: engine,
  })
  const service = new Orders(orders, inventory, payments)
  return { clock, inventory, orders, payments, checkout, service }
}

// The cart of CART, as the customer fills it: a subtotal of 1500.
function appleAndPear(): Cart {
  const cart = new Cart()
  cart.add('apple', 2)
  cart.add('pear', 1)
  return cart
}

function withCoupon(usageLimit: number): PromotionEngine {
  const engine = new PromotionEngine()
  engine.addCoupon(saveTen(usageLimit))
  return engine
}

describe('checkout', () => {
  it('prices an order with the promotions of the engine', () => {
    const { checkout } = shopWith(engineWith({ id: 'ten', kind: 'percentage', percent: 10 }))
    const order = checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'card' })
    expect(order.lines).toEqual([
      { sku: 'apple', name: 'Apple', unitPrice: 250, quantity: 2 },
      { sku: 'pear', name: 'Pear', unitPrice: 1000, quantity: 1 },
    ])
    expect([order.subtotal, order.discounts, order.total]).toEqual([
      1500,
      [{ promotionId: 'ten', amount: 150 }],
      1350,
    ])
  })

  it('charges the payment the total after the discounts', () => {
    const { checkout, payments } = shopWith(
      engineWith({ id: 'ten', kind: 'percentage', percent: 10 })
    )
    checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'card' })
    expect(payments.charges()).toEqual([{ id: 'payment-1', token: 'card', amount: 1350 }])
  })

  it('quotes a cart with the promotions of the engine', () => {
    const { checkout } = shopWith(engineWith({ id: 'off', kind: 'fixed', amount: 200 }))
    expect(checkout.quote(appleAndPear())).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 200 }],
      total: 1300,
    })
  })

  it('quotes a cart with coupons without using them', () => {
    const { checkout } = shopWith(withCoupon(1))
    checkout.quote(appleAndPear(), ['SAVE10'])
    expect(checkout.quote(appleAndPear(), ['SAVE10']).total).toBe(1350)
    const order = checkout.placeOrder({
      cart: appleAndPear(),
      paymentToken: 'card',
      coupons: ['SAVE10'],
    })
    expect(order.discounts).toEqual([{ promotionId: 'save-ten', amount: 150 }])
  })

  it('redeems the coupons of an order at checkout', () => {
    const { checkout } = shopWith(withCoupon(1))
    const request = { cart: appleAndPear(), paymentToken: 'card', coupons: ['SAVE10'] }
    expect(checkout.placeOrder(request).total).toBe(1350)
    expect(thrown(() => checkout.placeOrder(request))).toBe(
      'coupon SAVE10 has reached its usage limit'
    )
  })

  it('checks the expiry of a coupon on the date of the clock', () => {
    const { checkout, clock } = shopWith(withCoupon(5))
    clock.set('2026-04-01')
    expect(
      thrown(() =>
        checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'card', coupons: ['SAVE10'] })
      )
    ).toBe('coupon SAVE10 has expired')
  })

  it('fails with the error of the engine and changes nothing', () => {
    const { checkout, orders, payments, inventory } = shopWith(withCoupon(5))
    expect(
      thrown(() =>
        checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'card', coupons: ['NOPE'] })
      )
    ).toBe('unknown coupon NOPE')
    expect(orders.list()).toEqual([])
    expect(payments.charges()).toEqual([])
    expect(inventory.available('apple')).toBe(10)
  })

  it('uses no coupon when the payment is declined', () => {
    const { checkout, payments } = shopWith(withCoupon(1))
    payments.decline('stolen')
    expect(
      thrown(() =>
        checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'stolen', coupons: ['SAVE10'] })
      )
    ).toBe('payment declined')
    const order = checkout.placeOrder({
      cart: appleAndPear(),
      paymentToken: 'card',
      coupons: ['SAVE10'],
    })
    expect(order.total).toBe(1350)
  })

  it('uses no coupon when the stock is short', () => {
    const { checkout } = shopWith(withCoupon(1))
    const short = new Cart()
    short.add('pear', 6)
    expect(
      thrown(() => checkout.placeOrder({ cart: short, paymentToken: 'card', coupons: ['SAVE10'] }))
    ).toBe('not enough stock of pear: 5 available')
    const order = checkout.placeOrder({
      cart: appleAndPear(),
      paymentToken: 'card',
      coupons: ['SAVE10'],
    })
    expect(order.total).toBe(1350)
  })

  it('charges no payment when the total is zero', () => {
    const { checkout, payments } = shopWith(
      engineWith({ id: 'free', kind: 'percentage', percent: 100 })
    )
    const order = checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'card' })
    expect([order.total, order.paymentId, order.status]).toEqual([0, '', 'paid'])
    expect(payments.charges()).toEqual([])
  })

  it('refunds the total that was charged when an order is cancelled', () => {
    const { checkout, payments, service } = shopWith(
      engineWith({ id: 'ten', kind: 'percentage', percent: 10 })
    )
    const order = checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'card' })
    service.cancel(order.id)
    expect(payments.refunds()).toEqual([{ paymentId: 'payment-1', amount: 1350 }])
  })

  it('cancels an order with no payment without a refund', () => {
    const { checkout, payments, service, inventory } = shopWith(
      engineWith({ id: 'free', kind: 'percentage', percent: 100 })
    )
    const order = checkout.placeOrder({ cart: appleAndPear(), paymentToken: 'card' })
    service.cancel(order.id)
    expect(service.order(order.id).status).toBe('cancelled')
    expect(payments.refunds()).toEqual([])
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 10, reserved: 0 })
  })

  it('does not give back the coupons of a cancelled order', () => {
    const { checkout, service } = shopWith(withCoupon(1))
    const request = { cart: appleAndPear(), paymentToken: 'card', coupons: ['SAVE10'] }
    service.cancel(checkout.placeOrder(request).id)
    expect(thrown(() => checkout.placeOrder(request))).toBe(
      'coupon SAVE10 has reached its usage limit'
    )
  })
})
