// The checkout: it prices a cart from the catalogue, reserves the stock,
// charges the payment and places the order. A checkout that fails changes
// nothing.

import { Cart } from '../domain/cart.ts'
import type { Clock } from '../domain/dates.ts'
import { invalid, notFound } from '../domain/errors.ts'
import { PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'
import { sum, times } from '../domain/money.ts'
import type { Order, OrderLine, OrderRepository } from '../domain/order.ts'
import type { PaymentGateway } from '../domain/payment.ts'
import type { Line, Quote } from '../domain/promotion.ts'
import type { Catalogue } from './catalogue.ts'
import type { Customers } from './customers.ts'
import type { Inventory } from './inventory.ts'
import type { PromotionEngine } from './promotion-engine.ts'

export interface CheckoutDeps {
  catalogue: Catalogue
  inventory: Inventory
  orders: OrderRepository
  payments: PaymentGateway
  clock: Clock
  ids: IdSource
  promotions?: PromotionEngine
  customers?: Customers // needed only to place orders for customers
}

export interface CheckoutRequest {
  cart: Cart
  paymentToken: string
  coupons?: string[]
  customerId?: string // absent for a guest
}

// A line of a cart that the checkout would reject, and why.
export interface CartProblem {
  sku: string
  problem: 'unknown product' | 'discontinued' | 'not enough stock'
  available?: number // with `not enough stock`
}

export class Checkout {
  constructor(private readonly deps: CheckoutDeps) {}

  // The problems of a cart, line by line, in cart order, without throwing:
  // what the customer must change before the checkout can place the order.
  public problems(cart: Cart): CartProblem[] {
    const problems: CartProblem[] = []
    for (const line of cart.lines()) {
      if (!this.deps.catalogue.has(line.sku)) {
        problems.push({ sku: line.sku, problem: 'unknown product' })
      } else if (this.deps.catalogue.product(line.sku).discontinued) {
        problems.push({ sku: line.sku, problem: 'discontinued' })
      } else {
        const available = this.deps.inventory.available(line.sku)
        if (line.quantity > available) {
          problems.push({ sku: line.sku, problem: 'not enough stock', available })
        }
      }
    }
    return problems
  }

  // Changes the cart so that the checkout can place it: removes each line of
  // a product that is unknown, discontinued or out of stock, and lowers each
  // other line to the stock available. It gives the problems that it fixed.
  public fit(cart: Cart): CartProblem[] {
    const problems = this.problems(cart)
    for (const problem of problems) {
      if (problem.available !== undefined && problem.available > 0) {
        cart.setQuantity(problem.sku, problem.available)
      } else {
        cart.remove(problem.sku)
      }
    }
    return problems
  }

  // The price of the cart, as the checkout would charge it now.
  public quote(cart: Cart, coupons: string[] = []): Quote {
    return this.price(this.lines(cart), coupons)
  }

  // A new cart with the lines of an earlier order, for a customer who wants
  // to buy the same again. The lines of products that are no longer on sale
  // are left out.
  public reorder(orderId: string): Cart {
    const order = this.deps.orders.get(orderId)
    if (order === undefined) {
      throw notFound('order', orderId)
    }
    const cart = new Cart()
    for (const line of order.lines) {
      if (this.deps.catalogue.has(line.sku) && !this.deps.catalogue.product(line.sku).discontinued) {
        cart.add(line.sku, line.quantity)
      }
    }
    return cart
  }

  // The coupons are redeemed only once the payment has gone through, so a
  // checkout that fails uses no coupon. Each order line keeps its part of each
  // discount, which a return reverses.
  public placeOrder(request: CheckoutRequest): Order {
    const customerId = request.customerId
    if (customerId !== undefined) {
      this.customer(customerId)
    }
    const lines = this.lines(request.cart)
    const coupons = request.coupons ?? []
    const quote = this.price(lines, coupons)
    const parts =
      this.deps.promotions?.discountsByLine(engineLines(lines), coupons, this.deps.clock.today()) ??
      []
    parts.forEach((discounts, i) => {
      if (discounts.length > 0) lines[i].discounts = discounts
    })
    const id = this.deps.ids.next(PREFIX.order)
    this.deps.inventory.reserve(
      id,
      lines.map((line) => ({ sku: line.sku, quantity: line.quantity }))
    )
    let paymentId = ''
    if (quote.total > 0) {
      try {
        paymentId = this.deps.payments.charge(request.paymentToken, quote.total).id
      } catch (error) {
        this.deps.inventory.release(id)
        throw error
      }
    }
    this.deps.promotions?.redeem(engineLines(lines), coupons, this.deps.clock.today())
    const order: Order = {
      id,
      lines,
      subtotal: quote.subtotal,
      discounts: quote.discounts,
      total: quote.total,
      status: 'paid',
      paymentId,
      placedOn: this.deps.clock.today(),
    }
    if (customerId !== undefined) {
      order.customerId = customerId
    }
    this.deps.orders.save(order)
    return order
  }

  private customer(id: string): void {
    if (this.deps.customers === undefined) {
      throw invalid('this checkout takes no customers')
    }
    this.deps.customers.open(id)
  }

  // The lines of the cart, in cart order, at the prices of the catalogue.
  private lines(cart: Cart): OrderLine[] {
    if (cart.isEmpty()) {
      throw invalid('the cart is empty')
    }
    return cart.lines().map((line) => {
      const product = this.deps.catalogue.product(line.sku)
      if (product.discontinued) {
        throw invalid(`product ${line.sku} is discontinued`)
      }
      return {
        sku: line.sku,
        name: product.name,
        unitPrice: product.unitPrice,
        quantity: line.quantity,
      }
    })
  }

  // Without a promotions engine, the cart costs its subtotal.
  private price(lines: OrderLine[], coupons: string[]): Quote {
    if (this.deps.promotions !== undefined) {
      return this.deps.promotions.quote(engineLines(lines), coupons, this.deps.clock.today())
    }
    if (coupons.length > 0) {
      throw invalid('this checkout takes no coupons')
    }
    const subtotal = sum(lines.map((line) => times(line.unitPrice, line.quantity)))
    return { subtotal, discounts: [], total: subtotal }
  }
}

function engineLines(lines: OrderLine[]): Line[] {
  return lines.map((line) => ({
    sku: line.sku,
    unitPrice: line.unitPrice,
    quantity: line.quantity,
  }))
}
