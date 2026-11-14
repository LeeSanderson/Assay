// Shipping: a paid order goes out in one shipment. Creating a shipment
// prices it by the carrier's rate for the zone of the address; dispatching
// it ships the order (so its stock leaves the inventory) and tells the
// customer; the carrier then delivers it.

import { checkAddress, formatAddress } from '../domain/customer.ts'
import type { Address, Notifier } from '../domain/customer.ts'
import { checkPeriod, daysBetween, within } from '../domain/dates.ts'
import type { Clock, IsoDate } from '../domain/dates.ts'
import { conflict, invalid, notFound } from '../domain/errors.ts'
import type { ShopEvent } from '../domain/event.ts'
import { PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'
import type { Cents } from '../domain/money.ts'
import { unitsOf } from '../domain/order.ts'
import type { Order } from '../domain/order.ts'
import {
  checkNext,
  checkRate,
  checkTrackingCode,
  checkZone,
  costOf,
  parcelsOf,
  zoneOf,
} from '../domain/shipment.ts'
import type { Shipment, ShipmentRepository, ShippingRate, Zone } from '../domain/shipment.ts'
import type { Customers } from './customers.ts'
import type { Orders } from './orders.ts'

export interface ShippingDeps {
  shipments: ShipmentRepository
  orders: Orders
  customers: Customers
  notifier: Notifier
  clock: Clock
  ids: IdSource
}

export class Shipping {
  private readonly rates = new Map<Zone, ShippingRate>()

  constructor(private readonly deps: ShippingDeps) {}

  // Sets the rate of the carrier for a zone, in place of the one it had.
  public setRate(rate: ShippingRate): void {
    checkRate(rate)
    this.rates.set(rate.zone, { ...rate })
  }

  public rate(zone: Zone): ShippingRate {
    checkZone(zone)
    const rate = this.rates.get(zone)
    if (rate === undefined) {
      throw invalid(`no rate for zone ${zone}`)
    }
    return { ...rate }
  }

  // What the carrier would charge to send the order to the address.
  public quote(orderId: string, address: Address): Cents {
    checkAddress(address)
    const order = this.deps.orders.order(orderId)
    return costOf(this.rate(zoneOf(address.country)), unitsOf(order), order.total)
  }

  // Creates the shipment of a paid order, to the address, or else to the
  // address of the order's customer.
  public createShipment(orderId: string, address?: Address): Shipment {
    const order = this.deps.orders.checkPaid(orderId)
    if (this.find(orderId) !== undefined) {
      throw conflict(`order ${orderId} already has a shipment`)
    }
    const to = address ?? this.addressOf(order)
    checkAddress(to)
    const zone = zoneOf(to.country)
    const rate = this.rate(zone)
    const units = unitsOf(order)
    const shipment: Shipment = {
      id: this.deps.ids.next(PREFIX.shipment),
      orderId,
      address: { ...to },
      zone,
      units,
      parcels: parcelsOf(rate, units).length,
      cost: costOf(rate, units, order.total),
      status: 'pending',
      createdOn: this.deps.clock.today(),
    }
    this.deps.shipments.save(shipment)
    return shipment
  }

  // Hands the shipment to the carrier: the order ships, and its customer, if
  // it has one, gets a message with the tracking code.
  public dispatch(id: string, trackingCode: string): Shipment {
    checkTrackingCode(trackingCode)
    const shipment = this.shipment(id)
    checkNext(shipment, 'dispatched')
    this.deps.orders.ship(shipment.orderId)
    const dispatched: Shipment = {
      ...shipment,
      status: 'dispatched',
      trackingCode,
      dispatchedOn: this.deps.clock.today(),
    }
    this.deps.shipments.save(dispatched)
    this.notify(dispatched)
    return dispatched
  }

  public deliver(id: string): Shipment {
    const shipment = this.shipment(id)
    checkNext(shipment, 'delivered')
    const delivered: Shipment = {
      ...shipment,
      status: 'delivered',
      deliveredOn: this.deps.clock.today(),
    }
    this.deps.shipments.save(delivered)
    return delivered
  }

  // Cancels a pending shipment; its order stays as it is.
  public cancel(id: string): Shipment {
    const shipment = this.shipment(id)
    checkNext(shipment, 'cancelled')
    const cancelled: Shipment = { ...shipment, status: 'cancelled' }
    this.deps.shipments.save(cancelled)
    return cancelled
  }

  // Cancels the pending shipment of an order that was cancelled, if it has
  // one. The composition root (shop.ts) calls it on `order-cancelled`.
  public onOrderCancelled(event: ShopEvent): void {
    const shipment = this.find(event.subject)
    if (shipment !== undefined && shipment.status === 'pending') {
      this.cancel(shipment.id)
    }
  }

  public shipment(id: string): Shipment {
    const shipment = this.deps.shipments.get(id)
    if (shipment === undefined) {
      throw notFound('shipment', id)
    }
    return shipment
  }

  // The shipment of an order: an error when it has none.
  public shipmentOf(orderId: string): Shipment {
    this.deps.orders.order(orderId)
    const shipment = this.find(orderId)
    if (shipment === undefined) {
      throw invalid(`order ${orderId} has no shipment`)
    }
    return shipment
  }

  // The shipments not yet dispatched, in the order that they were created.
  public pending(): Shipment[] {
    return this.deps.shipments.list().filter((shipment) => shipment.status === 'pending')
  }

  // The dispatched shipments that the carrier has not delivered more than
  // `days` days after their dispatch, on the date of the clock.
  public overdue(days: number): Shipment[] {
    const today = this.deps.clock.today()
    return this.deps.shipments
      .list()
      .filter(
        (shipment) =>
          shipment.status === 'dispatched' &&
          shipment.dispatchedOn !== undefined &&
          daysBetween(shipment.dispatchedOn, today) > days
      )
  }

  // The shipment of the order that is not cancelled, if it has one.
  // The shipments delivered in the period, in the order that they were
  // created.
  public deliveredBetween(from: IsoDate, to: IsoDate): Shipment[] {
    checkPeriod(from, to)
    return this.deps.shipments
      .list()
      .filter((s) => s.deliveredOn !== undefined && within(s.deliveredOn, from, to))
  }

  // The days from dispatch to delivery, over the delivered shipments, on
  // average and rounded down; 0 when none has been delivered.
  public averageDeliveryDays(): number {
    const days = this.deps.shipments
      .list()
      .filter((s) => s.dispatchedOn !== undefined && s.deliveredOn !== undefined)
      .map((s) => daysBetween(s.dispatchedOn as IsoDate, s.deliveredOn as IsoDate))
    return days.length === 0 ? 0 : Math.floor(days.reduce((a, b) => a + b, 0) / days.length)
  }

  // The shipment of the order that is not cancelled, if it has one.
  private find(orderId: string): Shipment | undefined {
    return this.deps.shipments
      .list()
      .find((shipment) => shipment.orderId === orderId && shipment.status !== 'cancelled')
  }

  private addressOf(order: Order): Address {
    if (order.customerId === undefined) {
      throw invalid(`order ${order.id} has no address`)
    }
    return this.deps.customers.addressOf(order.customerId)
  }

  private notify(shipment: Shipment): void {
    const order = this.deps.orders.order(shipment.orderId)
    if (order.customerId === undefined) {
      return
    }
    const customer = this.deps.customers.customer(order.customerId)
    this.deps.notifier.send({
      to: customer.email,
      subject: `Order ${order.id} has shipped`,
      body:
        `Hello ${customer.name}, your order ${order.id} is on its way to ` +
        `${formatAddress(shipment.address)}. Tracking code: ${shipment.trackingCode}.`,
    })
  }
}
