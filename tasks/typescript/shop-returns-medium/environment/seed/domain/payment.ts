// Payments. The shop charges a payment token at checkout, through a payment
// gateway outside the shop, and refunds the whole payment when an order is
// cancelled. The gateway is behind this interface; adapters/memory.ts holds
// the one in memory.

import type { Cents } from './money.ts'

export interface Payment {
  id: string
  token: string
  amount: Cents
}

export interface Refund {
  paymentId: string
  amount: Cents
}

export interface PaymentGateway {
  charge(token: string, amount: Cents): Payment
  refund(paymentId: string): Refund
}
