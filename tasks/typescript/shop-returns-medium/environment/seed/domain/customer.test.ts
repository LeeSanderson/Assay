import { describe, expect, it } from '@jest/globals'
import {
  balanceOf,
  checkAddress,
  checkEmail,
  copyCustomer,
  formatAddress,
  normaliseEmail,
} from './customer.ts'
import type { AccountEntry, Address, Customer } from './customer.ts'

const HOME: Address = { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' }

describe('customers', () => {
  it('keeps an email address in lower case without spaces', () => {
    expect(normaliseEmail('  Ada@Example.COM ')).toBe('ada@example.com')
  })

  it('rejects a text that is not an email address', () => {
    expect(() => checkEmail('ada.example.com')).toThrow('ada.example.com is not an email address')
    expect(() => checkEmail('Ada@Example.com')).not.toThrow()
  })

  it('checks each part of an address', () => {
    expect(() => checkAddress(HOME)).not.toThrow()
    expect(() => checkAddress({ ...HOME, city: ' ' })).toThrow('city must not be empty')
    expect(() => checkAddress({ ...HOME, country: 'gb' })).toThrow('gb is not a country code')
  })

  it('writes an address on one line', () => {
    expect(formatAddress(HOME)).toBe('1 High St, Leeds LS1 1AA, GB')
  })

  it('copies a customer with its address', () => {
    const customer: Customer = {
      id: 'customer-1',
      name: 'Ada',
      email: 'ada@example.com',
      address: HOME,
      registeredOn: '2026-03-10',
    }
    const copy = copyCustomer(customer)
    copy.address!.city = 'York'
    expect(customer.address?.city).toBe('Leeds')
  })
})

describe('accounts', () => {
  it('keeps a balance of each kind of entry', () => {
    const entry = (kind: 'credit' | 'points', amount: number): AccountEntry => ({
      id: 'entry',
      customerId: 'customer-1',
      kind,
      amount,
      reason: 'test',
      on: '2026-03-10',
    })
    const entries = [entry('credit', 500), entry('points', 12), entry('credit', -200)]
    expect(balanceOf(entries, 'credit')).toBe(300)
    expect(balanceOf(entries, 'points')).toBe(12)
  })
})
