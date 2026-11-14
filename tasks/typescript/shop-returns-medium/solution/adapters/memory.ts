// The adapters of the shop in memory: a store for each kind of record, the
// payment gateway, and the outbox of the messages to customers. Each store
// keeps copies: what it gives back is a copy of what it holds, and what it
// saves is a copy of what it is given, so that a caller never changes a
// record that the store holds.

import { copyCustomer } from '../domain/customer.ts'
import type {
  AccountEntry,
  AccountRepository,
  Customer,
  CustomerRepository,
  Message,
  Notifier,
} from '../domain/customer.ts'
import { conflict, declined, notFound } from '../domain/errors.ts'
import { copyEvent } from '../domain/event.ts'
import type { EventStore, ShopEvent } from '../domain/event.ts'
import { PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'
import { copyInvoice } from '../domain/invoice.ts'
import type { Invoice, InvoiceRepository } from '../domain/invoice.ts'
import { checkCents, sum } from '../domain/money.ts'
import type { Cents } from '../domain/money.ts'
import { copyOrder } from '../domain/order.ts'
import type { Order, OrderRepository } from '../domain/order.ts'
import type { Payment, PaymentGateway, Refund } from '../domain/payment.ts'
import { copyProduct } from '../domain/product.ts'
import type { Product, ProductRepository } from '../domain/product.ts'
import { copyPurchase, copySupplier } from '../domain/purchase.ts'
import type {
  PurchaseOrder,
  PurchaseRepository,
  Supplier,
  SupplierRepository,
} from '../domain/purchase.ts'
import { copyShipment } from '../domain/shipment.ts'
import type { Shipment, ShipmentRepository } from '../domain/shipment.ts'
import { copyLevel, copyReservation } from '../domain/stock.ts'
import type {
  Reservation,
  StockLevel,
  StockMovement,
  StockRepository,
} from '../domain/stock.ts'

// Records by key, in the order that each key was first saved.
class Table<T> {
  private readonly rows = new Map<string, T>()

  constructor(
    private readonly key: (row: T) => string,
    private readonly copy: (row: T) => T
  ) {}

  get(key: string): T | undefined {
    const row = this.rows.get(key)
    return row === undefined ? undefined : this.copy(row)
  }

  save(row: T): void {
    this.rows.set(this.key(row), this.copy(row))
  }

  remove(key: string): void {
    this.rows.delete(key)
  }

  list(): T[] {
    return [...this.rows.values()].map(this.copy)
  }
}

// --- The stores ---------------------------------------------------------------

export class InMemoryProductRepository implements ProductRepository {
  private readonly table = new Table<Product>((product) => product.sku, copyProduct)

  get(sku: string): Product | undefined {
    return this.table.get(sku)
  }

  save(product: Product): void {
    this.table.save(product)
  }

  list(): Product[] {
    return this.table.list()
  }
}

export class InMemoryStockRepository implements StockRepository {
  private readonly levels = new Table<StockLevel>((level) => level.sku, copyLevel)
  private readonly held = new Table<Reservation>((r) => r.orderId, copyReservation)
  private readonly log: StockMovement[] = []

  get(sku: string): StockLevel | undefined {
    return this.levels.get(sku)
  }

  save(level: StockLevel): void {
    this.levels.save(level)
  }

  list(): StockLevel[] {
    return this.levels.list()
  }

  reservation(orderId: string): Reservation | undefined {
    return this.held.get(orderId)
  }

  reservations(): Reservation[] {
    return this.held.list()
  }

  saveReservation(reservation: Reservation): void {
    this.held.save(reservation)
  }

  removeReservation(orderId: string): void {
    this.held.remove(orderId)
  }

  addMovement(movement: StockMovement): void {
    this.log.push({ ...movement })
  }

  movements(): StockMovement[] {
    return this.log.map((movement) => ({ ...movement }))
  }
}

export class InMemoryOrderRepository implements OrderRepository {
  private readonly table = new Table<Order>((order) => order.id, copyOrder)

  get(id: string): Order | undefined {
    return this.table.get(id)
  }

  save(order: Order): void {
    this.table.save(order)
  }

  // The orders in the order that they were first saved.
  list(): Order[] {
    return this.table.list()
  }
}

export class InMemoryCustomerRepository implements CustomerRepository {
  private readonly table = new Table<Customer>((customer) => customer.id, copyCustomer)

  get(id: string): Customer | undefined {
    return this.table.get(id)
  }

  save(customer: Customer): void {
    this.table.save(customer)
  }

  list(): Customer[] {
    return this.table.list()
  }
}

export class InMemoryAccountRepository implements AccountRepository {
  private readonly log: AccountEntry[] = []

  add(entry: AccountEntry): void {
    this.log.push({ ...entry })
  }

  entries(customerId: string): AccountEntry[] {
    return this.log.filter((entry) => entry.customerId === customerId).map((e) => ({ ...e }))
  }
}

export class InMemoryShipmentRepository implements ShipmentRepository {
  private readonly table = new Table<Shipment>((shipment) => shipment.id, copyShipment)

  get(id: string): Shipment | undefined {
    return this.table.get(id)
  }

  save(shipment: Shipment): void {
    this.table.save(shipment)
  }

  list(): Shipment[] {
    return this.table.list()
  }
}

export class InMemoryInvoiceRepository implements InvoiceRepository {
  private readonly table = new Table<Invoice>((invoice) => invoice.id, copyInvoice)

  get(id: string): Invoice | undefined {
    return this.table.get(id)
  }

  save(invoice: Invoice): void {
    this.table.save(invoice)
  }

  list(): Invoice[] {
    return this.table.list()
  }
}

export class InMemorySupplierRepository implements SupplierRepository {
  private readonly table = new Table<Supplier>((supplier) => supplier.id, copySupplier)

  get(id: string): Supplier | undefined {
    return this.table.get(id)
  }

  save(supplier: Supplier): void {
    this.table.save(supplier)
  }

  list(): Supplier[] {
    return this.table.list()
  }
}

export class InMemoryPurchaseRepository implements PurchaseRepository {
  private readonly table = new Table<PurchaseOrder>((order) => order.id, copyPurchase)

  get(id: string): PurchaseOrder | undefined {
    return this.table.get(id)
  }

  save(order: PurchaseOrder): void {
    this.table.save(order)
  }

  list(): PurchaseOrder[] {
    return this.table.list()
  }
}

export class InMemoryEventStore implements EventStore {
  private readonly log: ShopEvent[] = []

  append(event: ShopEvent): void {
    this.log.push(copyEvent(event))
  }

  list(): ShopEvent[] {
    return this.log.map(copyEvent)
  }
}

// --- The payment gateway ------------------------------------------------------

// A payment gateway in memory: it accepts every token but the declined ones,
// and keeps each charge and each refund.
export class InMemoryPaymentGateway implements PaymentGateway {
  private readonly declined = new Set<string>()
  private readonly payments: Payment[] = []
  private readonly refunded: Refund[] = []

  constructor(private readonly ids: IdSource) {}

  decline(token: string): void {
    this.declined.add(token)
  }

  charge(token: string, amount: Cents): Payment {
    checkCents(amount, 'amount', 1)
    if (this.declined.has(token)) {
      throw declined('payment declined')
    }
    const payment = { id: this.ids.next(PREFIX.payment), token, amount }
    this.payments.push(payment)
    return { ...payment }
  }

  refund(paymentId: string): Refund {
    const payment = this.payment(paymentId)
    if (this.refunded.some((r) => r.paymentId === paymentId)) {
      throw conflict(`payment ${paymentId} is already refunded`)
    }
    const refund = { paymentId, amount: payment.amount }
    this.refunded.push(refund)
    return { ...refund }
  }

  // Refunds part of a payment. The refunds of a payment never add up to more
  // than its amount.
  refundPart(paymentId: string, amount: Cents): Refund {
    const payment = this.payment(paymentId)
    checkCents(amount, 'amount', 1)
    const done = sum(this.refunded.filter((r) => r.paymentId === paymentId).map((r) => r.amount))
    if (amount > payment.amount - done) {
      throw conflict(`payment ${paymentId} has ${payment.amount - done} left to refund`)
    }
    const refund = { paymentId, amount }
    this.refunded.push(refund)
    return { ...refund }
  }

  charges(): Payment[] {
    return this.payments.map((payment) => ({ ...payment }))
  }

  refunds(): Refund[] {
    return this.refunded.map((refund) => ({ ...refund }))
  }

  // What the shop holds of the payments: the charges less the refunds.
  balance(): Cents {
    return (
      sum(this.payments.map((payment) => payment.amount)) -
      sum(this.refunded.map((refund) => refund.amount))
    )
  }

  private payment(id: string): Payment {
    const payment = this.payments.find((p) => p.id === id)
    if (payment === undefined) {
      throw notFound('payment', id)
    }
    return payment
  }
}

// --- The outbox ---------------------------------------------------------------

// A notifier in memory: it keeps each message that the shop sends, in the
// order that the shop sent them, instead of sending an email.
export class InMemoryOutbox implements Notifier {
  private readonly messages: Message[] = []

  send(message: Message): void {
    this.messages.push({ ...message })
  }

  sent(): Message[] {
    return this.messages.map((message) => ({ ...message }))
  }

  // The messages sent to one address.
  sentTo(email: string): Message[] {
    return this.sent().filter((message) => message.to === email)
  }
}
