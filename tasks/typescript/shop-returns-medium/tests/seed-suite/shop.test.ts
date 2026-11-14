import { describe, expect, it } from '@jest/globals'
import { Cart } from './cart.ts'
import { createShop } from './shop.ts'

const LEEDS = { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' }

// The whole shop, with apples at 250 and pears at 1000, 20 of each, a
// domestic rate, and Ada (customer-1), who lives in Leeds.
function shop() {
  const shop = createShop({
    today: '2026-03-10',
    rates: [{ zone: 'domestic', firstUnit: 400, perExtraUnit: 100 }],
  })
  shop.catalogue.addProduct('apple', 'Apple', 250)
  shop.catalogue.addProduct('pear', 'Pear', 1000)
  shop.inventory.receive('apple', 20)
  shop.inventory.receive('pear', 20)
  const ada = shop.customers.register('Ada', 'ada@example.com', LEEDS)
  const place = (...items: [string, number][]) => {
    const cart = new Cart()
    for (const [sku, quantity] of items) cart.add(sku, quantity)
    return shop.checkout.placeOrder({ cart, paymentToken: 'card', customerId: ada.id })
  }
  return { ...shop, ada, place }
}

describe('the shop', () => {
  it('records each change of an order, a shipment, an invoice and a customer', () => {
    const { events, shipping, invoicing, place } = shop()
    const order = place(['apple', 2])
    const shipment = shipping.createShipment(order.id)
    shipping.dispatch(shipment.id, 'TRK-1')
    invoicing.issue(order.id)
    expect(events.all().map((event) => [event.type, event.subject])).toEqual([
      ['customer-registered', 'customer-1'],
      ['order-placed', order.id],
      ['shipment-created', shipment.id],
      ['order-shipped', order.id],
      ['shipment-dispatched', shipment.id],
      ['invoice-issued', 'invoice-1'],
    ])
  })

  it('awards loyalty points when an order is placed, and takes them back when it is cancelled', () => {
    const { accounts, orders, ada, place } = shop()
    const first = place(['pear', 2])
    place(['apple', 3])
    expect(accounts.points(ada.id)).toBe(27)
    orders.cancel(first.id)
    expect(accounts.points(ada.id)).toBe(7)
  })

  it('cancels the pending shipment of a cancelled order', () => {
    const { orders, shipping, place } = shop()
    const order = place(['apple', 1])
    const shipment = shipping.createShipment(order.id)
    orders.cancel(order.id)
    expect(shipping.shipment(shipment.id).status).toBe('cancelled')
  })

  it('prices orders with its promotions engine', () => {
    const { promotions, place, reports } = shop()
    promotions.addPromotion({ id: 'ten', kind: 'percentage', percent: 10 })
    expect(place(['pear', 1]).total).toBe(900)
    expect(reports.promotionUsage()).toEqual([{ promotionId: 'ten', orders: 1, amount: 100 }])
  })

  it('tells the customer when an order ships', () => {
    const { outbox, shipping, place } = shop()
    const order = place(['apple', 1])
    shipping.dispatch(shipping.createShipment(order.id).id, 'TRK-7')
    expect(outbox.sentTo('ada@example.com').map((message) => message.subject)).toEqual([
      `Order ${order.id} has shipped`,
    ])
  })

  it('brings stock in through purchasing and sells it', () => {
    const { purchasing, inventory, place } = shop()
    const supplier = purchasing.addSupplier('Orchard', 'sales@orchard.example', 3)
    const draft = purchasing.draft(supplier.id)
    purchasing.addLine(draft.id, 'apple', 30, 120)
    purchasing.send(draft.id)
    purchasing.receiveAll(draft.id)
    place(['apple', 45])
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 50, reserved: 45 })
  })

  it('reports its sales, stock and shipping together', () => {
    const { reports, shipping, place } = shop()
    const order = place(['apple', 4])
    shipping.createShipment(order.id)
    expect(reports.salesSummary('2026-03-01', '2026-03-31').revenue).toBe(1000)
    expect(reports.monthlyMargin()).toEqual([
      { month: '2026-03', revenue: 1000, shipping: 700, margin: 300 },
    ])
    expect(reports.stockValuation().total).toBe(25000)
  })

  it('uses the tax rate that it is given', () => {
    const custom = createShop({ today: '2026-03-10', taxRate: 0 })
    custom.catalogue.addProduct('apple', 'Apple', 250)
    custom.inventory.receive('apple', 1)
    const cart = new Cart()
    cart.add('apple', 1)
    const order = custom.checkout.placeOrder({ cart, paymentToken: 'card' })
    expect(custom.invoicing.issue(order.id).tax).toBe(0)
  })
})
