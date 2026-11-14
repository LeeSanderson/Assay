// Recording stores: each wraps a store, saves through it, and tells the event
// log of each change that a rule of domain/event.ts turns into an event. A
// service that saves through a recording store does not know of the event
// log; the composition root (shop.ts) puts the recording stores in place.

import type { Customer, CustomerRepository } from '../domain/customer.ts'
import { customerChange, invoiceChange, orderChange, shipmentChange } from '../domain/event.ts'
import type { Change, ChangeSink } from '../domain/event.ts'
import type { Invoice, InvoiceRepository } from '../domain/invoice.ts'
import type { Order, OrderRepository } from '../domain/order.ts'
import type { Shipment, ShipmentRepository } from '../domain/shipment.ts'

interface Store<T> {
  get(id: string): T | undefined
  save(record: T): void
  list(): T[]
}

// Saves, then records the change, if the rule gives one.
class Recording<T extends { id: string }> implements Store<T> {
  constructor(
    private readonly inner: Store<T>,
    private readonly sink: ChangeSink,
    private readonly rule: (before: T | undefined, after: T) => Change | undefined
  ) {}

  get(id: string): T | undefined {
    return this.inner.get(id)
  }

  save(record: T): void {
    const before = this.inner.get(record.id)
    this.inner.save(record)
    const change = this.rule(before, record)
    if (change !== undefined) {
      this.sink.record(change)
    }
  }

  list(): T[] {
    return this.inner.list()
  }
}

export class RecordingOrderRepository extends Recording<Order> implements OrderRepository {
  constructor(inner: OrderRepository, sink: ChangeSink) {
    super(inner, sink, orderChange)
  }
}

export class RecordingShipmentRepository
  extends Recording<Shipment>
  implements ShipmentRepository
{
  constructor(inner: ShipmentRepository, sink: ChangeSink) {
    super(inner, sink, shipmentChange)
  }
}

export class RecordingInvoiceRepository extends Recording<Invoice> implements InvoiceRepository {
  constructor(inner: InvoiceRepository, sink: ChangeSink) {
    super(inner, sink, invoiceChange)
  }
}

export class RecordingCustomerRepository
  extends Recording<Customer>
  implements CustomerRepository
{
  constructor(inner: CustomerRepository, sink: ChangeSink) {
    super(inner, sink, customerChange)
  }
}
