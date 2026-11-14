// Purchasing: the suppliers of the shop and its purchase orders. A purchase
// order is drafted, filled with lines, and sent, which emails it to the
// supplier; each delivery is received into the inventory. A purchase order
// can be cancelled until anything of it has been received.

import type { Notifier } from '../domain/customer.ts'
import { addDays } from '../domain/dates.ts'
import type { Clock, IsoDate } from '../domain/dates.ts'
import { checkQuantity, invalid, notFound, wrongState } from '../domain/errors.ts'
import { compareText, PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'
import { formatCents } from '../domain/money.ts'
import type { Cents } from '../domain/money.ts'
import {
  checkPurchaseLine,
  checkPurchaseStatus,
  checkSupplier,
  costOfPurchase,
  isReceived,
  outstanding,
} from '../domain/purchase.ts'
import type {
  PurchaseOrder,
  PurchaseRepository,
  Supplier,
  SupplierRepository,
} from '../domain/purchase.ts'
import type { StockLine } from '../domain/stock.ts'
import type { Catalogue } from './catalogue.ts'
import type { Inventory } from './inventory.ts'

export interface PurchasingDeps {
  suppliers: SupplierRepository
  purchases: PurchaseRepository
  catalogue: Catalogue
  inventory: Inventory
  notifier: Notifier
  clock: Clock
  ids: IdSource
}

export class Purchasing {
  constructor(private readonly deps: PurchasingDeps) {}

  public addSupplier(name: string, email: string, leadTimeDays: number): Supplier {
    checkSupplier(name, email, leadTimeDays)
    const supplier = { id: this.deps.ids.next(PREFIX.supplier), name, email, leadTimeDays }
    this.deps.suppliers.save(supplier)
    return supplier
  }

  public supplier(id: string): Supplier {
    const supplier = this.deps.suppliers.get(id)
    if (supplier === undefined) {
      throw notFound('supplier', id)
    }
    return supplier
  }

  // Drafts an empty purchase order to the supplier.
  public draft(supplierId: string): PurchaseOrder {
    this.supplier(supplierId)
    const order: PurchaseOrder = {
      id: this.deps.ids.next(PREFIX.purchase),
      supplierId,
      lines: [],
      status: 'draft',
      createdOn: this.deps.clock.today(),
    }
    this.deps.purchases.save(order)
    return order
  }

  // Adds a line of a product of the catalogue to a draft; a SKU that is on
  // the draft already gets the quantity added, at the new unit cost.
  public addLine(id: string, sku: string, quantity: number, unitCost: Cents): PurchaseOrder {
    checkPurchaseLine(sku, quantity, unitCost)
    const order = this.purchase(id)
    checkPurchaseStatus(order, 'draft')
    this.deps.catalogue.product(sku)
    const lines = order.lines.map((line) => ({ ...line }))
    const same = lines.find((line) => line.sku === sku)
    if (same === undefined) {
      lines.push({ sku, quantity, unitCost, received: 0 })
    } else {
      same.quantity += quantity
      same.unitCost = unitCost
    }
    return this.save({ ...order, lines })
  }

  // Drafts a purchase order to the supplier with a line for each SKU whose
  // available stock, with what is on order, is below `threshold`: enough to
  // bring it up to `target`, at the unit cost that `costs` gives for the SKU.
  // A SKU with no cost is left out. It gives no draft when no SKU is short.
  public draftReorder(
    supplierId: string,
    costs: Readonly<Record<string, Cents>>,
    threshold: number,
    target: number
  ): PurchaseOrder | undefined {
    this.supplier(supplierId)
    const short = Object.keys(costs)
      .sort(compareText)
      .map((sku) => ({
        sku,
        have: this.deps.inventory.available(sku) + this.onOrder(sku),
      }))
      .filter(({ have }) => have < threshold)
    if (short.length === 0) {
      return undefined
    }
    let order = this.draft(supplierId)
    for (const { sku, have } of short) {
      order = this.addLine(order.id, sku, target - have, costs[sku])
    }
    return order
  }

  public removeLine(id: string, sku: string): PurchaseOrder {
    const order = this.purchase(id)
    checkPurchaseStatus(order, 'draft')
    if (!order.lines.some((line) => line.sku === sku)) {
      throw invalid(`SKU ${sku} is not in purchase ${id}`)
    }
    return this.save({ ...order, lines: order.lines.filter((line) => line.sku !== sku) })
  }

  // Sends a draft with at least one line to its supplier, by email, and
  // expects it after the lead time of the supplier.
  public send(id: string): PurchaseOrder {
    const order = this.purchase(id)
    checkPurchaseStatus(order, 'draft')
    if (order.lines.length === 0) {
      throw invalid(`purchase ${id} has no lines`)
    }
    const supplier = this.supplier(order.supplierId)
    const today = this.deps.clock.today()
    const sent = this.save({
      ...order,
      status: 'sent',
      sentOn: today,
      expectedOn: addDays(today, supplier.leadTimeDays),
    })
    this.deps.notifier.send({
      to: supplier.email,
      subject: `Purchase order ${id}`,
      body: [
        ...sent.lines.map(
          (line) => `${line.quantity} x ${line.sku} at ${formatCents(line.unitCost)}`
        ),
        `Total: ${formatCents(costOfPurchase(sent))}`,
      ].join('\n'),
    })
    return sent
  }

  // Receives a delivery against a sent purchase order: each line goes into
  // the inventory. A delivery cannot hold more of a SKU than is outstanding.
  // The purchase order is received once every unit has come in.
  public receive(id: string, delivery: readonly StockLine[]): PurchaseOrder {
    const order = this.purchase(id)
    checkPurchaseStatus(order, 'sent')
    const lines = order.lines.map((line) => ({ ...line }))
    for (const item of delivery) {
      checkQuantity(item.quantity)
      const line = lines.find((l) => l.sku === item.sku)
      if (line === undefined) {
        throw invalid(`SKU ${item.sku} is not in purchase ${id}`)
      }
      if (item.quantity > outstanding(line)) {
        throw invalid(`${item.sku} has ${outstanding(line)} outstanding`)
      }
      line.received += item.quantity
    }
    for (const item of delivery) {
      this.deps.inventory.receive(item.sku, item.quantity)
    }
    const updated: PurchaseOrder = { ...order, lines }
    if (isReceived(updated)) {
      updated.status = 'received'
    }
    return this.save(updated)
  }

  // Receives every unit that is outstanding on a sent purchase order.
  public receiveAll(id: string): PurchaseOrder {
    const order = this.purchase(id)
    const delivery = order.lines
      .filter((line) => outstanding(line) > 0)
      .map((line) => ({ sku: line.sku, quantity: outstanding(line) }))
    return this.receive(id, delivery)
  }

  // The suppliers, in the order that they were added.
  public suppliers(): Supplier[] {
    return this.deps.suppliers.list()
  }

  public cancel(id: string): PurchaseOrder {
    const order = this.purchase(id)
    if (order.status !== 'draft' && order.status !== 'sent') {
      throw wrongState('purchase', id, order.status)
    }
    if (order.lines.some((line) => line.received > 0)) {
      throw invalid(`purchase ${id} has been received in part`)
    }
    return this.save({ ...order, status: 'cancelled' })
  }

  public purchase(id: string): PurchaseOrder {
    const order = this.deps.purchases.get(id)
    if (order === undefined) {
      throw notFound('purchase', id)
    }
    return order
  }

  // The units of a SKU that are on sent purchase orders and have not come in.
  public onOrder(sku: string): number {
    return this.deps.purchases
      .list()
      .filter((order) => order.status === 'sent')
      .flatMap((order) => order.lines)
      .filter((line) => line.sku === sku)
      .reduce((total, line) => total + outstanding(line), 0)
  }

  // The sent purchase orders that were expected before the date.
  public late(date: IsoDate): PurchaseOrder[] {
    return this.deps.purchases
      .list()
      .filter(
        (order) =>
          order.status === 'sent' && order.expectedOn !== undefined && order.expectedOn < date
      )
  }

  // What the shop has spent with a supplier, over its purchase orders that
  // were not cancelled, for every unit ordered.
  public spendWith(supplierId: string): Cents {
    this.supplier(supplierId)
    return this.deps.purchases
      .list()
      .filter((order) => order.supplierId === supplierId && order.status !== 'cancelled')
      .reduce((total, order) => total + costOfPurchase(order), 0)
  }

  private save(order: PurchaseOrder): PurchaseOrder {
    this.deps.purchases.save(order)
    return order
  }
}
