import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import {
  InMemoryCustomerRepository,
  InMemoryOrderRepository,
  InMemoryOutbox,
  InMemoryPaymentGateway,
  InMemoryProductRepository,
  InMemoryShipmentRepository,
  InMemoryStockRepository,
} from '../adapters/memory.ts'
import { Cart } from '../domain/cart.ts'
import type { Address } from '../domain/customer.ts'
import { Catalogue } from './catalogue.ts'
import { Checkout } from './checkout.ts'
import { Customers } from './customers.ts'
import { Inventory } from './inventory.ts'
import { Orders } from './orders.ts'
import { Shipping } from './shipping.ts'

const LEEDS: Address = { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' }
const PARIS: Address = { line1: '2 Rue Haute', city: 'Paris', postcode: '75001', country: 'FR' }

// A shop with apples at 250 and pears at 1000, 20 of each, and the rates of
// a carrier for the home zone and Europe.
function shop() {
  const ids = new SequentialIds()
  const clock = new FixedClock('2026-03-10')
  const catalogue = new Catalogue(new InMemoryProductRepository())
  catalogue.addProduct('apple', 'Apple', 250)
  catalogue.addProduct('pear', 'Pear', 1000)
  const inventory = new Inventory(new InMemoryStockRepository())
  inventory.receive('apple', 20)
  inventory.receive('pear', 20)
  const repository = new InMemoryOrderRepository()
  const payments = new InMemoryPaymentGateway(ids)
  const customers = new Customers({ repository: new InMemoryCustomerRepository(), clock, ids })
  const checkout = new Checkout({
    catalogue,
    inventory,
    orders: repository,
    payments,
    clock,
    ids,
    customers,
  })
  const orders = new Orders(repository, inventory, payments)
  const outbox = new InMemoryOutbox()
  const shipping = new Shipping({
    shipments: new InMemoryShipmentRepository(),
    orders,
    customers,
    notifier: outbox,
    clock,
    ids,
  })
  shipping.setRate({ zone: 'domestic', firstUnit: 400, perExtraUnit: 100, freeFrom: 5000 })
  shipping.setRate({ zone: 'europe', firstUnit: 900, perExtraUnit: 200, maxUnitsPerParcel: 3 })
  // place(customerId, ['apple', 2], ...) places an order and gives its id.
  const place = (customerId: string | undefined, ...items: [string, number][]): string => {
    const cart = new Cart()
    for (const [sku, quantity] of items) cart.add(sku, quantity)
    return checkout.placeOrder({ cart, paymentToken: 'card', customerId }).id
  }
  return { clock, inventory, customers, orders, outbox, shipping, place }
}

describe('rates', () => {
  it('quotes what the carrier charges to send an order to an address', () => {
    const { shipping, place } = shop()
    const id = place(undefined, ['apple', 4])
    expect(shipping.quote(id, LEEDS)).toBe(700)
    // Two parcels to Europe: three units, then one.
    expect(shipping.quote(id, PARIS)).toBe(2200)
  })

  it('sends an order free from the free shipping total of its zone', () => {
    const { shipping, place } = shop()
    expect(shipping.quote(place(undefined, ['pear', 5]), LEEDS)).toBe(0)
  })

  it('rejects a zone with no rate', () => {
    const { shipping, place } = shop()
    const id = place(undefined, ['apple', 1])
    expect(() => shipping.quote(id, { ...LEEDS, country: 'US' })).toThrow('no rate for zone world')
    expect(() => shipping.rate('moon' as never)).toThrow('unknown zone moon')
  })
})

describe('shipments', () => {
  it('creates the shipment of a paid order to an address', () => {
    const { shipping, place } = shop()
    const id = place(undefined, ['apple', 4], ['pear', 3])
    expect(shipping.createShipment(id, PARIS)).toEqual({
      id: 'shipment-1',
      orderId: id,
      address: PARIS,
      zone: 'europe',
      units: 7,
      parcels: 3,
      cost: 3500,
      status: 'pending',
      createdOn: '2026-03-10',
    })
  })

  it('sends a shipment to the address of the customer of the order', () => {
    const { shipping, customers, place } = shop()
    const ada = customers.register('Ada', 'ada@example.com', LEEDS)
    const shipment = shipping.createShipment(place(ada.id, ['apple', 1]))
    expect([shipment.address, shipment.zone, shipment.cost]).toEqual([LEEDS, 'domestic', 400])
  })

  it('rejects a shipment with no address', () => {
    const { shipping, customers, place } = shop()
    expect(() => shipping.createShipment(place(undefined, ['apple', 1]))).toThrow(
      'order order-1 has no address'
    )
    const bob = customers.register('Bob', 'bob@example.com')
    expect(() => shipping.createShipment(place(bob.id, ['apple', 1]))).toThrow(
      'customer customer-1 has no address'
    )
  })

  it('rejects a second shipment of an order, and a shipment of an order that is not paid', () => {
    const { shipping, orders, place } = shop()
    const id = place(undefined, ['apple', 1])
    shipping.createShipment(id, LEEDS)
    expect(() => shipping.createShipment(id, LEEDS)).toThrow(
      `order ${id} already has a shipment`
    )
    const cancelled = place(undefined, ['apple', 1])
    orders.cancel(cancelled)
    expect(() => shipping.createShipment(cancelled, LEEDS)).toThrow(
      `order ${cancelled} is cancelled`
    )
  })

  it('finds the shipment of an order', () => {
    const { shipping, place } = shop()
    const id = place(undefined, ['apple', 1])
    const shipment = shipping.createShipment(id, LEEDS)
    expect(shipping.shipmentOf(id)).toEqual(shipment)
    expect(shipping.shipment(shipment.id)).toEqual(shipment)
    expect(() => shipping.shipmentOf(place(undefined, ['apple', 1]))).toThrow(
      'order order-2 has no shipment'
    )
    expect(() => shipping.shipment('shipment-9')).toThrow('unknown shipment shipment-9')
  })
})

describe('dispatch and delivery', () => {
  it('dispatches a shipment, which ships its order', () => {
    const { clock, shipping, orders, inventory, place } = shop()
    const id = place(undefined, ['apple', 3])
    const shipment = shipping.createShipment(id, LEEDS)
    clock.set('2026-03-11')
    const dispatched = shipping.dispatch(shipment.id, 'TRK-1')
    expect([dispatched.status, dispatched.trackingCode, dispatched.dispatchedOn]).toEqual([
      'dispatched',
      'TRK-1',
      '2026-03-11',
    ])
    expect(orders.order(id).status).toBe('shipped')
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 17, reserved: 0 })
  })

  it('tells the customer that the order has shipped', () => {
    const { shipping, customers, outbox, place } = shop()
    const ada = customers.register('Ada', 'ada@example.com', LEEDS)
    const id = place(ada.id, ['apple', 1])
    shipping.dispatch(shipping.createShipment(id).id, 'TRK-9')
    expect(outbox.sent()).toEqual([
      {
        to: 'ada@example.com',
        subject: `Order ${id} has shipped`,
        body:
          `Hello Ada, your order ${id} is on its way to 1 High St, Leeds LS1 1AA, GB. ` +
          'Tracking code: TRK-9.',
      },
    ])
  })

  it('sends no message for a guest order', () => {
    const { shipping, outbox, place } = shop()
    const id = place(undefined, ['apple', 1])
    shipping.dispatch(shipping.createShipment(id, LEEDS).id, 'TRK-1')
    expect(outbox.sent()).toEqual([])
  })

  it('delivers a dispatched shipment, once', () => {
    const { clock, shipping, place } = shop()
    const shipment = shipping.createShipment(place(undefined, ['apple', 1]), LEEDS)
    expect(() => shipping.deliver(shipment.id)).toThrow('shipment shipment-1 is pending')
    shipping.dispatch(shipment.id, 'TRK-1')
    clock.set('2026-03-13')
    expect(shipping.deliver(shipment.id).deliveredOn).toBe('2026-03-13')
    expect(() => shipping.dispatch(shipment.id, 'TRK-2')).toThrow(
      'shipment shipment-1 is delivered'
    )
  })

  it('rejects an empty tracking code', () => {
    const { shipping, place } = shop()
    const shipment = shipping.createShipment(place(undefined, ['apple', 1]), LEEDS)
    expect(() => shipping.dispatch(shipment.id, ' ')).toThrow('tracking code must not be empty')
  })

  it('does not dispatch the shipment of an order that was cancelled', () => {
    const { shipping, orders, place } = shop()
    const id = place(undefined, ['apple', 1])
    const shipment = shipping.createShipment(id, LEEDS)
    orders.cancel(id)
    expect(() => shipping.dispatch(shipment.id, 'TRK-1')).toThrow(`order ${id} is cancelled`)
    expect(shipping.shipment(shipment.id).status).toBe('pending')
  })
})

describe('cancellation', () => {
  it('cancels a pending shipment, and lets the order have a new one', () => {
    const { shipping, place } = shop()
    const id = place(undefined, ['apple', 1])
    const first = shipping.createShipment(id, LEEDS)
    expect(shipping.cancel(first.id).status).toBe('cancelled')
    const second = shipping.createShipment(id, PARIS)
    expect(shipping.shipmentOf(id).id).toBe(second.id)
  })

  it('cancels the pending shipment of a cancelled order', () => {
    const { shipping, orders, place } = shop()
    const id = place(undefined, ['apple', 1])
    const shipment = shipping.createShipment(id, LEEDS)
    orders.cancel(id)
    shipping.onOrderCancelled({
      id: 'event-1',
      type: 'order-cancelled',
      subject: id,
      on: '2026-03-10',
      data: {},
    })
    expect(shipping.shipment(shipment.id).status).toBe('cancelled')
  })
})

describe('tracking the carrier', () => {
  it('lists the pending shipments and the overdue ones', () => {
    const { clock, shipping, place } = shop()
    const first = shipping.createShipment(place(undefined, ['apple', 1]), LEEDS)
    const second = shipping.createShipment(place(undefined, ['apple', 1]), LEEDS)
    shipping.dispatch(first.id, 'TRK-1')
    expect(shipping.pending().map((s) => s.id)).toEqual([second.id])
    clock.set('2026-03-15')
    expect(shipping.overdue(5)).toEqual([])
    expect(shipping.overdue(4).map((s) => s.id)).toEqual([first.id])
  })

  it('works out the days from dispatch to delivery', () => {
    const { clock, shipping, place } = shop()
    expect(shipping.averageDeliveryDays()).toBe(0)
    for (const days of [2, 5]) {
      clock.set('2026-03-10')
      const shipment = shipping.createShipment(place(undefined, ['apple', 1]), LEEDS)
      shipping.dispatch(shipment.id, 'TRK')
      clock.advance(days)
      shipping.deliver(shipment.id)
    }
    expect(shipping.averageDeliveryDays()).toBe(3)
    expect(shipping.deliveredBetween('2026-03-15', '2026-03-31').map((s) => s.id)).toEqual([
      'shipment-2',
    ])
  })
})
