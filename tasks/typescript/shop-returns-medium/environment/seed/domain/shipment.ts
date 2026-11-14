// Shipping. A paid order goes out in one shipment, to an address. The cost
// of a shipment is what the carrier charges the shop, by the zone of the
// address and the number of units; the customer does not pay it, so it is
// not part of the order. A shipment is pending until it is dispatched (the
// order then ships), and then delivered.

import { check, checkNotEmpty, wrongState } from './errors.ts'
import type { IsoDate } from './dates.ts'
import type { Address } from './customer.ts'
import { checkCents, sum } from './money.ts'
import type { Cents } from './money.ts'

export type Zone = 'domestic' | 'europe' | 'world'

export const ZONES: readonly Zone[] = ['domestic', 'europe', 'world']

// The shop is in GB. The countries of Europe that the carrier counts as one
// zone, by their two-letter codes.
const HOME = 'GB'
const EUROPE: readonly string[] = [
  'AT', 'BE', 'CH', 'DE', 'DK', 'ES', 'FI', 'FR', 'IE', 'IT', 'NL', 'NO', 'PL', 'PT', 'SE',
]

// The price list of the carrier for one zone: a price for the first unit, a
// price for each other unit, and an order total from which the shop sends
// the shipment free, when the zone has one.
export interface ShippingRate {
  zone: Zone
  firstUnit: Cents
  perExtraUnit: Cents
  freeFrom?: Cents
  maxUnitsPerParcel?: number // no limit when absent
}

export type ShipmentStatus = 'pending' | 'dispatched' | 'delivered' | 'cancelled'

export interface Shipment {
  id: string
  orderId: string
  address: Address
  zone: Zone
  units: number
  parcels: number
  cost: Cents
  status: ShipmentStatus
  createdOn: IsoDate
  trackingCode?: string // from its dispatch
  dispatchedOn?: IsoDate
  deliveredOn?: IsoDate
}

export interface ShipmentRepository {
  get(id: string): Shipment | undefined
  save(shipment: Shipment): void
  list(): Shipment[] // in the order that they were created
}

export function zoneOf(country: string): Zone {
  if (country === HOME) return 'domestic'
  return EUROPE.includes(country) ? 'europe' : 'world'
}

export function checkZone(zone: string): void {
  check((ZONES as readonly string[]).includes(zone), `unknown zone ${zone}`)
}

export function checkRate(rate: ShippingRate): void {
  checkZone(rate.zone)
  checkCents(rate.firstUnit, 'first unit price')
  checkCents(rate.perExtraUnit, 'extra unit price')
  if (rate.freeFrom !== undefined) {
    checkCents(rate.freeFrom, 'free shipping total', 1)
  }
  if (rate.maxUnitsPerParcel !== undefined) {
    check(
      Number.isInteger(rate.maxUnitsPerParcel) && rate.maxUnitsPerParcel >= 1,
      'a parcel must take at least 1 unit'
    )
  }
}

// The units in each parcel of a shipment: full parcels of the most units
// that a parcel takes, then one parcel with the rest. One parcel when the
// rate sets no limit.
export function parcelsOf(rate: ShippingRate, units: number): number[] {
  const most = rate.maxUnitsPerParcel
  if (most === undefined || units <= most) {
    return [units]
  }
  const parcels = Array.from({ length: Math.floor(units / most) }, () => most)
  if (units % most > 0) {
    parcels.push(units % most)
  }
  return parcels
}

// What the carrier charges for `units` units, for an order of `orderTotal`:
// each parcel costs the first unit price and the extra unit price for each
// other unit in it.
export function costOf(rate: ShippingRate, units: number, orderTotal: Cents): Cents {
  if (rate.freeFrom !== undefined && orderTotal >= rate.freeFrom) {
    return 0
  }
  return sum(
    parcelsOf(rate, units).map(
      (inParcel) => rate.firstUnit + rate.perExtraUnit * Math.max(0, inParcel - 1)
    )
  )
}

// The statuses that a shipment can move to from each status. A status that
// is not here moves nowhere.
const NEXT: Partial<Record<ShipmentStatus, readonly ShipmentStatus[]>> = {
  pending: ['dispatched', 'cancelled'],
  dispatched: ['delivered'],
}

// Checks that the shipment can move to the status: `shipment <id> is
// <status>` when not.
export function checkNext(shipment: Shipment, status: ShipmentStatus): void {
  if (!(NEXT[shipment.status] ?? []).includes(status)) {
    throw wrongState('shipment', shipment.id, shipment.status)
  }
}

export function checkTrackingCode(code: string): void {
  checkNotEmpty(code, 'tracking code')
}

export function copyShipment(shipment: Shipment): Shipment {
  return { ...shipment, address: { ...shipment.address } }
}
