import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import {
  InMemoryOutbox,
  InMemoryProductRepository,
  InMemoryPurchaseRepository,
  InMemoryStockRepository,
  InMemorySupplierRepository,
} from '../adapters/memory.ts'
import { Catalogue } from './catalogue.ts'
import { Inventory } from './inventory.ts'
import { Purchasing } from './purchasing.ts'

// A shop that sells apples and pears, with one supplier, Orchard
// (supplier-1), who delivers 5 days after an order.
function shop() {
  const ids = new SequentialIds()
  const clock = new FixedClock('2026-03-10')
  const catalogue = new Catalogue(new InMemoryProductRepository())
  catalogue.addProduct('apple', 'Apple', 250)
  catalogue.addProduct('pear', 'Pear', 1000)
  const inventory = new Inventory(new InMemoryStockRepository())
  const outbox = new InMemoryOutbox()
  const purchasing = new Purchasing({
    suppliers: new InMemorySupplierRepository(),
    purchases: new InMemoryPurchaseRepository(),
    catalogue,
    inventory,
    notifier: outbox,
    clock,
    ids,
  })
  const orchard = purchasing.addSupplier('Orchard', 'sales@orchard.example', 5)
  return { clock, inventory, outbox, purchasing, orchard }
}

describe('suppliers', () => {
  it('adds a supplier and finds it by id', () => {
    const { purchasing, orchard } = shop()
    expect(orchard).toEqual({
      id: 'supplier-1',
      name: 'Orchard',
      email: 'sales@orchard.example',
      leadTimeDays: 5,
    })
    expect(purchasing.supplier('supplier-1')).toEqual(orchard)
    expect(purchasing.suppliers()).toEqual([orchard])
    expect(() => purchasing.supplier('supplier-9')).toThrow('unknown supplier supplier-9')
  })
})

describe('drafts', () => {
  it('drafts a purchase order and adds lines to it', () => {
    const { purchasing, orchard } = shop()
    const draft = purchasing.draft(orchard.id)
    purchasing.addLine(draft.id, 'apple', 10, 120)
    purchasing.addLine(draft.id, 'pear', 2, 600)
    const order = purchasing.addLine(draft.id, 'apple', 5, 110)
    expect(order).toEqual({
      id: 'purchase-1',
      supplierId: 'supplier-1',
      lines: [
        { sku: 'apple', quantity: 15, unitCost: 110, received: 0 },
        { sku: 'pear', quantity: 2, unitCost: 600, received: 0 },
      ],
      status: 'draft',
      createdOn: '2026-03-10',
    })
  })

  it('rejects a line of an unknown product, and a broken line', () => {
    const { purchasing, orchard } = shop()
    const draft = purchasing.draft(orchard.id)
    expect(() => purchasing.addLine(draft.id, 'kiwi', 1, 100)).toThrow('unknown product kiwi')
    expect(() => purchasing.addLine(draft.id, 'apple', 1, 0)).toThrow(
      'unit cost must be at least 1'
    )
  })

  it('removes a line from a draft', () => {
    const { purchasing, orchard } = shop()
    const draft = purchasing.draft(orchard.id)
    purchasing.addLine(draft.id, 'apple', 10, 120)
    expect(purchasing.removeLine(draft.id, 'apple').lines).toEqual([])
    expect(() => purchasing.removeLine(draft.id, 'apple')).toThrow(
      'SKU apple is not in purchase purchase-1'
    )
  })
})

describe('sending', () => {
  it('sends a draft to its supplier and expects it after the lead time', () => {
    const { purchasing, orchard, outbox } = shop()
    const draft = purchasing.draft(orchard.id)
    purchasing.addLine(draft.id, 'apple', 10, 120)
    purchasing.addLine(draft.id, 'pear', 2, 600)
    const sent = purchasing.send(draft.id)
    expect([sent.status, sent.sentOn, sent.expectedOn]).toEqual([
      'sent',
      '2026-03-10',
      '2026-03-15',
    ])
    expect(outbox.sent()).toEqual([
      {
        to: 'sales@orchard.example',
        subject: 'Purchase order purchase-1',
        body: '10 x apple at 1.20\n2 x pear at 6.00\nTotal: 24.00',
      },
    ])
  })

  it('rejects sending an empty draft, or a purchase order twice', () => {
    const { purchasing, orchard } = shop()
    const draft = purchasing.draft(orchard.id)
    expect(() => purchasing.send(draft.id)).toThrow('purchase purchase-1 has no lines')
    purchasing.addLine(draft.id, 'apple', 1, 120)
    purchasing.send(draft.id)
    expect(() => purchasing.send(draft.id)).toThrow('purchase purchase-1 is sent')
    expect(() => purchasing.addLine(draft.id, 'apple', 1, 120)).toThrow(
      'purchase purchase-1 is sent'
    )
  })
})

describe('receiving', () => {
  function sentOrder() {
    const fixture = shop()
    const draft = fixture.purchasing.draft(fixture.orchard.id)
    fixture.purchasing.addLine(draft.id, 'apple', 10, 120)
    fixture.purchasing.addLine(draft.id, 'pear', 2, 600)
    fixture.purchasing.send(draft.id)
    return { ...fixture, id: draft.id }
  }

  it('receives a delivery into the inventory, in part', () => {
    const { purchasing, inventory, id } = sentOrder()
    const order = purchasing.receive(id, [{ sku: 'apple', quantity: 4 }])
    expect(order.status).toBe('sent')
    expect(order.lines.map((line) => line.received)).toEqual([4, 0])
    expect(inventory.level('apple').onHand).toBe(4)
    expect(purchasing.onOrder('apple')).toBe(6)
  })

  it('is received once every unit has come in', () => {
    const { purchasing, inventory, id } = sentOrder()
    purchasing.receive(id, [{ sku: 'apple', quantity: 4 }])
    expect(purchasing.receiveAll(id).status).toBe('received')
    expect([inventory.level('apple').onHand, inventory.level('pear').onHand]).toEqual([10, 2])
    expect(purchasing.onOrder('apple')).toBe(0)
  })

  it('rejects a delivery of more than is outstanding, and changes nothing', () => {
    const { purchasing, inventory, id } = sentOrder()
    expect(() =>
      purchasing.receive(id, [
        { sku: 'apple', quantity: 4 },
        { sku: 'pear', quantity: 3 },
      ])
    ).toThrow('pear has 2 outstanding')
    expect(() => purchasing.receive(id, [{ sku: 'fig', quantity: 1 }])).toThrow(
      `SKU fig is not in purchase ${id}`
    )
    expect(inventory.level('apple').onHand).toBe(0)
  })

  it('lists the purchase orders that are late', () => {
    const { clock, purchasing, id } = sentOrder()
    clock.set('2026-03-15')
    expect(purchasing.late('2026-03-15')).toEqual([])
    expect(purchasing.late('2026-03-16').map((order) => order.id)).toEqual([id])
  })
})

describe('cancelling and reordering', () => {
  it('cancels a purchase order until anything of it has come in', () => {
    const { purchasing, orchard } = shop()
    const first = purchasing.draft(orchard.id)
    expect(purchasing.cancel(first.id).status).toBe('cancelled')
    expect(() => purchasing.cancel(first.id)).toThrow('purchase purchase-1 is cancelled')
    const second = purchasing.draft(orchard.id)
    purchasing.addLine(second.id, 'apple', 2, 100)
    purchasing.send(second.id)
    purchasing.receive(second.id, [{ sku: 'apple', quantity: 1 }])
    expect(() => purchasing.cancel(second.id)).toThrow(
      'purchase purchase-2 has been received in part'
    )
  })

  it('drafts a reorder of the SKUs that are short, counting what is on order', () => {
    const { purchasing, orchard, inventory } = shop()
    inventory.receive('apple', 3)
    inventory.receive('pear', 9)
    const order = purchasing.draftReorder(orchard.id, { pear: 600, apple: 120 }, 5, 10)
    expect(order?.lines).toEqual([{ sku: 'apple', quantity: 7, unitCost: 120, received: 0 }])
    purchasing.send(order!.id)
    expect(purchasing.draftReorder(orchard.id, { apple: 120 }, 5, 10)).toBeUndefined()
  })

  it('adds up what the shop spends with a supplier', () => {
    const { purchasing, orchard } = shop()
    const first = purchasing.draft(orchard.id)
    purchasing.addLine(first.id, 'apple', 10, 120)
    const second = purchasing.draft(orchard.id)
    purchasing.addLine(second.id, 'pear', 1, 600)
    purchasing.cancel(second.id)
    expect(purchasing.spendWith(orchard.id)).toBe(1200)
  })
})
