// The composition root: the whole shop, wired in memory. It builds each store
// and each service once, puts the recording stores between the services and
// the stores of orders, shipments, invoices and customers, so that the event
// log records their changes, and subscribes the accounts to the order events.
// The services take their stores and collaborators as arguments, so a test
// can also build any one of them on its own.

import { FixedClock, SequentialIds } from './adapters/clock.ts'
import {
  InMemoryAccountRepository,
  InMemoryCustomerRepository,
  InMemoryEventStore,
  InMemoryInvoiceRepository,
  InMemoryOrderRepository,
  InMemoryOutbox,
  InMemoryPaymentGateway,
  InMemoryProductRepository,
  InMemoryPurchaseRepository,
  InMemoryShipmentRepository,
  InMemoryStockRepository,
  InMemorySupplierRepository,
} from './adapters/memory.ts'
import {
  RecordingCustomerRepository,
  RecordingInvoiceRepository,
  RecordingOrderRepository,
  RecordingShipmentRepository,
} from './adapters/recording.ts'
import type { IsoDate } from './domain/dates.ts'
import type { ShippingRate } from './domain/shipment.ts'
import { Accounts } from './services/accounts.ts'
import { Catalogue } from './services/catalogue.ts'
import { Checkout } from './services/checkout.ts'
import { Customers } from './services/customers.ts'
import { EventLog } from './services/event-log.ts'
import { Inventory } from './services/inventory.ts'
import { Invoicing } from './services/invoicing.ts'
import { Orders } from './services/orders.ts'
import { PromotionEngine } from './services/promotion-engine.ts'
import { Purchasing } from './services/purchasing.ts'
import { Reports } from './services/reports.ts'
import { Returns } from './services/returns.ts'
import { Shipping } from './services/shipping.ts'

export interface ShopOptions {
  today: IsoDate // the date that the clock starts on
  taxRate?: number // in basis points; the standard rate when absent
  rates?: ShippingRate[] // the carrier's rates; none when absent
}

export function createShop(options: ShopOptions) {
  const clock = new FixedClock(options.today)
  const ids = new SequentialIds()
  const events = new EventLog({ store: new InMemoryEventStore(), clock, ids })

  const products = new InMemoryProductRepository()
  const stock = new InMemoryStockRepository()
  const orderStore = new RecordingOrderRepository(new InMemoryOrderRepository(), events)
  const shipmentStore = new RecordingShipmentRepository(new InMemoryShipmentRepository(), events)
  const invoiceStore = new RecordingInvoiceRepository(new InMemoryInvoiceRepository(), events)
  const customerStore = new RecordingCustomerRepository(new InMemoryCustomerRepository(), events)

  const payments = new InMemoryPaymentGateway(ids)
  const outbox = new InMemoryOutbox()
  const catalogue = new Catalogue(products)
  const inventory = new Inventory(stock)
  const promotions = new PromotionEngine()
  const customers = new Customers({ repository: customerStore, clock, ids })
  const accounts = new Accounts({
    repository: new InMemoryAccountRepository(),
    customers,
    clock,
    ids,
  })
  const checkout = new Checkout({
    catalogue,
    inventory,
    orders: orderStore,
    payments,
    clock,
    ids,
    promotions,
    customers,
  })
  const orders = new Orders(orderStore, inventory, payments)
  const returns = new Returns({ orders: orderStore, inventory, payments, clock, ids })
  const shipping = new Shipping({
    shipments: shipmentStore,
    orders,
    customers,
    notifier: outbox,
    clock,
    ids,
  })
  const invoicing = new Invoicing({
    invoices: invoiceStore,
    orders,
    clock,
    ids,
    taxRate: options.taxRate,
  })
  const purchasing = new Purchasing({
    suppliers: new InMemorySupplierRepository(),
    purchases: new InMemoryPurchaseRepository(),
    catalogue,
    inventory,
    notifier: outbox,
    clock,
    ids,
  })
  const reports = new Reports({
    orders: orderStore,
    products,
    stock,
    shipments: shipmentStore,
    customers: customerStore,
  })

  events.subscribe('order-placed', (event) => accounts.onOrderPlaced(event))
  events.subscribe('order-cancelled', (event) => accounts.onOrderCancelled(event))
  events.subscribe('order-cancelled', (event) => shipping.onOrderCancelled(event))
  for (const rate of options.rates ?? []) {
    shipping.setRate(rate)
  }

  return {
    clock,
    ids,
    payments,
    outbox,
    events,
    catalogue,
    inventory,
    promotions,
    customers,
    accounts,
    checkout,
    orders,
    returns,
    shipping,
    invoicing,
    purchasing,
    reports,
  }
}

export type Shop = ReturnType<typeof createShop>
