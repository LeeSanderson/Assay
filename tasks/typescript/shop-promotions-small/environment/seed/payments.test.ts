import { expect, it } from '@jest/globals'
import { SequentialIds } from './clock.ts'
import { InMemoryPaymentGateway } from './payments.ts'

function gateway(): InMemoryPaymentGateway {
  return new InMemoryPaymentGateway(new SequentialIds())
}

it('charges a token', () => {
  const payments = gateway()
  expect(payments.charge('card', 1500)).toEqual({ id: 'payment-1', token: 'card', amount: 1500 })
  expect(payments.charges()).toEqual([{ id: 'payment-1', token: 'card', amount: 1500 }])
})

it('rejects an amount below 1', () => {
  const payments = gateway()
  expect(() => payments.charge('card', 0)).toThrow('amount must be at least 1')
  expect(payments.charges()).toEqual([])
})

it('declines a declined token', () => {
  const payments = gateway()
  payments.decline('stolen')
  expect(() => payments.charge('stolen', 100)).toThrow('payment declined')
  expect(payments.charges()).toEqual([])
})

it('refunds a whole payment once', () => {
  const payments = gateway()
  const payment = payments.charge('card', 1500)
  expect(payments.refund(payment.id)).toEqual({ paymentId: 'payment-1', amount: 1500 })
  expect(() => payments.refund(payment.id)).toThrow('payment payment-1 is already refunded')
  expect(payments.refunds()).toEqual([{ paymentId: 'payment-1', amount: 1500 }])
})

it('rejects a refund of an unknown payment', () => {
  expect(() => gateway().refund('payment-9')).toThrow('unknown payment payment-9')
})
