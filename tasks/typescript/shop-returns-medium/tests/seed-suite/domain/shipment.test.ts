import { describe, expect, it } from '@jest/globals'
import { checkNext, checkRate, costOf, parcelsOf, zoneOf } from './shipment.ts'
import type { Shipment, ShippingRate } from './shipment.ts'

const DOMESTIC: ShippingRate = { zone: 'domestic', firstUnit: 400, perExtraUnit: 100 }

describe('zones', () => {
  it('puts the home country, Europe and the rest of the world in their zones', () => {
    expect(zoneOf('GB')).toBe('domestic')
    expect(zoneOf('FR')).toBe('europe')
    expect(zoneOf('US')).toBe('world')
  })

  it('rejects a rate for an unknown zone or with a broken price', () => {
    expect(() => checkRate({ ...DOMESTIC, zone: 'moon' as never })).toThrow('unknown zone moon')
    expect(() => checkRate({ ...DOMESTIC, firstUnit: -1 })).toThrow(
      'first unit price must be at least 0'
    )
    expect(() => checkRate({ ...DOMESTIC, maxUnitsPerParcel: 0 })).toThrow(
      'a parcel must take at least 1 unit'
    )
  })
})

describe('costs', () => {
  it('charges the first unit and each extra unit', () => {
    expect(costOf(DOMESTIC, 1, 500)).toBe(400)
    expect(costOf(DOMESTIC, 4, 500)).toBe(700)
  })

  it('sends an order free from the free shipping total', () => {
    const rate = { ...DOMESTIC, freeFrom: 5000 }
    expect(costOf(rate, 4, 4999)).toBe(700)
    expect(costOf(rate, 4, 5000)).toBe(0)
  })

  it('fills parcels up to the units that a parcel takes, and charges each parcel', () => {
    const rate = { ...DOMESTIC, maxUnitsPerParcel: 3 }
    expect(parcelsOf(rate, 7)).toEqual([3, 3, 1])
    expect(parcelsOf(rate, 6)).toEqual([3, 3])
    expect(parcelsOf(DOMESTIC, 7)).toEqual([7])
    expect(costOf(rate, 7, 500)).toBe(1600)
  })
})

describe('the status of a shipment', () => {
  const shipment = (status: Shipment['status']): Shipment => ({
    id: 'shipment-1',
    orderId: 'order-1',
    address: { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' },
    zone: 'domestic',
    units: 1,
    parcels: 1,
    cost: 400,
    status,
    createdOn: '2026-03-10',
  })

  it('moves from pending to dispatched to delivered', () => {
    expect(() => checkNext(shipment('pending'), 'dispatched')).not.toThrow()
    expect(() => checkNext(shipment('dispatched'), 'delivered')).not.toThrow()
    expect(() => checkNext(shipment('pending'), 'cancelled')).not.toThrow()
  })

  it('rejects a move out of order', () => {
    expect(() => checkNext(shipment('pending'), 'delivered')).toThrow(
      'shipment shipment-1 is pending'
    )
    expect(() => checkNext(shipment('delivered'), 'dispatched')).toThrow(
      'shipment shipment-1 is delivered'
    )
    expect(() => checkNext(shipment('dispatched'), 'cancelled')).toThrow(
      'shipment shipment-1 is dispatched'
    )
  })
})
