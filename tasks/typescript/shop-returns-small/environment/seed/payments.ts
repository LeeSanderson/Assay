// Payments: the shop charges a payment token at checkout and refunds the
// whole payment when an order is cancelled.

import type { IdSource } from './clock.ts'

export interface Payment {
  id: string
  token: string
  amount: number
}

export interface Refund {
  paymentId: string
  amount: number
}

export interface PaymentGateway {
  charge(token: string, amount: number): Payment
  refund(paymentId: string): Refund
}

// A gateway in memory: it accepts every token but the declined ones, and
// keeps each charge and each refund.
export class InMemoryPaymentGateway implements PaymentGateway {
  private readonly declined = new Set<string>()
  private readonly payments: Payment[] = []
  private readonly refunded: Refund[] = []

  constructor(private readonly ids: IdSource) {}

  decline(token: string): void {
    this.declined.add(token)
  }

  charge(token: string, amount: number): Payment {
    if (amount < 1) {
      throw new Error('amount must be at least 1')
    }
    if (this.declined.has(token)) {
      throw new Error('payment declined')
    }
    const payment = { id: this.ids.next('payment'), token, amount }
    this.payments.push(payment)
    return { ...payment }
  }

  refund(paymentId: string): Refund {
    const payment = this.payments.find((p) => p.id === paymentId)
    if (payment === undefined) {
      throw new Error(`unknown payment ${paymentId}`)
    }
    if (this.refunded.some((r) => r.paymentId === paymentId)) {
      throw new Error(`payment ${paymentId} is already refunded`)
    }
    const refund = { paymentId, amount: payment.amount }
    this.refunded.push(refund)
    return { ...refund }
  }

  charges(): Payment[] {
    return this.payments.map((payment) => ({ ...payment }))
  }

  refunds(): Refund[] {
    return this.refunded.map((refund) => ({ ...refund }))
  }
}
