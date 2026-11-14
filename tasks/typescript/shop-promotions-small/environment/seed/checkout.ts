// The checkout: it prices a cart from the catalogue, reserves the stock,
// charges the payment and places the order. A checkout that fails changes
// nothing.

import type { Cart } from './cart.ts'
import type { Catalogue } from './catalogue.ts'
import type { Clock, IdSource } from './clock.ts'
import type { Inventory } from './inventory.ts'
import type { Order, OrderLine, OrderRepository } from './orders.ts'
import type { PaymentGateway } from './payments.ts'
import type { PromotionEngine, Quote } from './promotions.ts'

export interface CheckoutDeps {
  catalogue: Catalogue
  inventory: Inventory
  orders: OrderRepository
  payments: PaymentGateway
  clock: Clock
  ids: IdSource
  promotions?: PromotionEngine
}

export interface CheckoutRequest {
  cart: Cart
  paymentToken: string
  coupons?: string[]
}

export class Checkout {
  constructor(private readonly deps: CheckoutDeps) {}

  // The price of the cart, as the checkout would charge it now.
  public quote(cart: Cart, coupons: string[] = []): Quote {
    return this.price(this.lines(cart))
  }

  public placeOrder(request: CheckoutRequest): Order {
    const lines = this.lines(request.cart)
    const quote = this.price(lines)
    const id = this.deps.ids.next('order')
    this.deps.inventory.reserve(
      id,
      lines.map((line) => ({ sku: line.sku, quantity: line.quantity }))
    )
    let paymentId: string
    try {
      paymentId = this.deps.payments.charge(request.paymentToken, quote.total).id
    } catch (error) {
      this.deps.inventory.release(id)
      throw error
    }
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
    this.deps.orders.save(order)
    return order
  }

  // The lines of the cart, in cart order, at the prices of the catalogue.
  private lines(cart: Cart): OrderLine[] {
    if (cart.isEmpty()) {
      throw new Error('the cart is empty')
    }
    return cart.lines().map((line) => {
      const product = this.deps.catalogue.product(line.sku)
      if (product.discontinued) {
        throw new Error(`product ${line.sku} is discontinued`)
      }
      return {
        sku: line.sku,
        name: product.name,
        unitPrice: product.unitPrice,
        quantity: line.quantity,
      }
    })
  }

  private price(lines: OrderLine[]): Quote {
    const subtotal = lines.reduce((sum, line) => sum + line.unitPrice * line.quantity, 0)
    return { subtotal, discounts: [], total: subtotal }
  }
}
