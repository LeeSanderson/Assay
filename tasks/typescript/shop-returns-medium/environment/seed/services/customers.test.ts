import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import { InMemoryCustomerRepository } from '../adapters/memory.ts'
import type { Address } from '../domain/customer.ts'
import { Customers } from './customers.ts'

const HOME: Address = { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' }

function customers() {
  const clock = new FixedClock('2026-03-10')
  const service = new Customers({
    repository: new InMemoryCustomerRepository(),
    clock,
    ids: new SequentialIds(),
  })
  return { clock, service }
}

describe('registration', () => {
  it('registers a customer with a lower-case email address', () => {
    const { service } = customers()
    expect(service.register(' Ada ', 'Ada@Example.com', HOME)).toEqual({
      id: 'customer-1',
      name: 'Ada',
      email: 'ada@example.com',
      address: HOME,
      registeredOn: '2026-03-10',
    })
  })

  it('registers a customer without an address', () => {
    const { service } = customers()
    const bob = service.register('Bob', 'bob@example.com')
    expect(bob.address).toBeUndefined()
    expect(() => service.addressOf(bob.id)).toThrow('customer customer-1 has no address')
  })

  it('rejects an email address that is already registered, in any case', () => {
    const { service } = customers()
    service.register('Ada', 'ada@example.com')
    expect(() => service.register('Ada two', 'ADA@example.com')).toThrow(
      'email ada@example.com is already registered'
    )
  })

  it('rejects a broken name, email address or address', () => {
    const { service } = customers()
    expect(() => service.register('', 'ada@example.com')).toThrow('name must not be empty')
    expect(() => service.register('Ada', 'ada')).toThrow('ada is not an email address')
    expect(() => service.register('Ada', 'ada@example.com', { ...HOME, postcode: '' })).toThrow(
      'postcode must not be empty'
    )
  })
})

describe('finding customers', () => {
  it('finds a customer by id or by email address', () => {
    const { service } = customers()
    const ada = service.register('Ada', 'ada@example.com')
    expect(service.customer(ada.id).name).toBe('Ada')
    expect(service.byEmail('ADA@EXAMPLE.COM').id).toBe(ada.id)
    expect(() => service.customer('customer-9')).toThrow('unknown customer customer-9')
    expect(() => service.byEmail('bob@example.com')).toThrow('unknown customer bob@example.com')
  })

  it('searches the names and email addresses in any case', () => {
    const { service } = customers()
    service.register('Ada Lovelace', 'ada@example.com')
    service.register('Bob', 'bob@lovelace.example')
    service.register('Cy', 'cy@example.com')
    expect(service.search('LOVELACE').map((c) => c.name)).toEqual(['Ada Lovelace', 'Bob'])
  })
})

describe('changes', () => {
  it('renames a customer and changes its email address', () => {
    const { service } = customers()
    const ada = service.register('Ada', 'ada@example.com')
    service.register('Bob', 'bob@example.com')
    expect(service.rename(ada.id, 'Ada L').name).toBe('Ada L')
    expect(service.changeEmail(ada.id, 'AL@example.com').email).toBe('al@example.com')
    expect(service.changeEmail(ada.id, 'al@example.com').email).toBe('al@example.com')
    expect(() => service.changeEmail(ada.id, 'bob@example.com')).toThrow(
      'email bob@example.com is already registered'
    )
  })

  it('moves a customer to a new address', () => {
    const { service } = customers()
    const ada = service.register('Ada', 'ada@example.com')
    service.moveTo(ada.id, HOME)
    expect(service.addressOf(ada.id)).toEqual(HOME)
  })

  it('closes the account of a customer once', () => {
    const { clock, service } = customers()
    const ada = service.register('Ada', 'ada@example.com')
    const bob = service.register('Bob', 'bob@example.com')
    clock.set('2026-04-01')
    expect(service.close(ada.id).closedOn).toBe('2026-04-01')
    expect(() => service.open(ada.id)).toThrow('customer customer-1 is closed')
    expect(() => service.close(ada.id)).toThrow('customer customer-1 is closed')
    expect(service.openCustomers().map((c) => c.id)).toEqual([bob.id])
  })
})
