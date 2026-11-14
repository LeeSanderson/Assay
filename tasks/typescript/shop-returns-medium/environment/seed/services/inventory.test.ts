import { describe, expect, it } from '@jest/globals'
import { InMemoryStockRepository } from '../adapters/memory.ts'
import { Inventory } from './inventory.ts'

function inventory(): Inventory {
  const stock = new Inventory(new InMemoryStockRepository())
  stock.receive('apple', 10)
  stock.receive('pear', 3)
  return stock
}

describe('stock on hand', () => {
  it('has no stock of a SKU that it has never received', () => {
    expect(new Inventory(new InMemoryStockRepository()).level('kiwi')).toEqual({
      sku: 'kiwi',
      onHand: 0,
      reserved: 0,
    })
  })

  it('receives stock', () => {
    const stock = inventory()
    stock.receive('apple', 5)
    expect(stock.level('apple')).toEqual({ sku: 'apple', onHand: 15, reserved: 0 })
    expect(stock.available('apple')).toBe(15)
  })

  it('rejects a received quantity below 1', () => {
    expect(() => inventory().receive('apple', 0)).toThrow('quantity must be at least 1')
  })

  it('writes off stock that is available', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'pear', quantity: 2 }])
    stock.writeOff('pear', 1)
    expect(stock.level('pear')).toEqual({ sku: 'pear', onHand: 2, reserved: 2 })
    expect(() => stock.writeOff('pear', 1)).toThrow('not enough stock of pear: 0 available')
  })

  it('lists the SKUs that it holds in SKU order', () => {
    const stock = inventory()
    stock.receive('fig', 1)
    expect(stock.skus()).toEqual(['apple', 'fig', 'pear'])
  })
})

describe('reservations', () => {
  it('reserves stock for an order', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
    expect(stock.level('apple')).toEqual({ sku: 'apple', onHand: 10, reserved: 4 })
    expect(stock.available('apple')).toBe(6)
  })

  it('reserves all the lines of an order or none of them', () => {
    const stock = inventory()
    expect(() =>
      stock.reserve('order-1', [
        { sku: 'apple', quantity: 2 },
        { sku: 'pear', quantity: 4 },
      ])
    ).toThrow('not enough stock of pear: 3 available')
    expect(stock.available('apple')).toBe(10)
    expect(stock.available('pear')).toBe(3)
  })

  it('reserves the lines of one SKU together', () => {
    const stock = inventory()
    expect(() =>
      stock.reserve('order-1', [
        { sku: 'pear', quantity: 2 },
        { sku: 'pear', quantity: 2 },
      ])
    ).toThrow('not enough stock of pear: 3 available')
    stock.reserve('order-2', [
      { sku: 'apple', quantity: 2 },
      { sku: 'apple', quantity: 3 },
    ])
    expect(stock.reserved('order-2')).toEqual([{ sku: 'apple', quantity: 5 }])
  })

  it('rejects a second reservation for the same order', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'apple', quantity: 1 }])
    expect(() => stock.reserve('order-1', [{ sku: 'pear', quantity: 1 }])).toThrow(
      'order order-1 already has a reservation'
    )
  })

  it('releases a reservation', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
    stock.release('order-1')
    expect(stock.level('apple')).toEqual({ sku: 'apple', onHand: 10, reserved: 0 })
    expect(stock.reserved('order-1')).toEqual([])
  })

  it('commits a reservation when the order ships', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
    stock.commit('order-1')
    expect(stock.level('apple')).toEqual({ sku: 'apple', onHand: 6, reserved: 0 })
  })

  it('rejects a release of an order with no reservation', () => {
    const stock = inventory()
    expect(() => stock.release('order-9')).toThrow('order order-9 has no reservation')
    expect(() => stock.commit('order-9')).toThrow('order order-9 has no reservation')
  })

  it('lists the orders that hold stock of a SKU', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
    stock.reserve('order-2', [
      { sku: 'pear', quantity: 1 },
      { sku: 'apple', quantity: 2 },
    ])
    expect(stock.reservedFor('apple')).toEqual([
      { orderId: 'order-1', quantity: 4 },
      { orderId: 'order-2', quantity: 2 },
    ])
  })
})

describe('counts', () => {
  it('counts stock but not below the reserved stock', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
    stock.count('apple', 7)
    expect(stock.level('apple')).toEqual({ sku: 'apple', onHand: 7, reserved: 4 })
    expect(() => stock.count('apple', 3)).toThrow('apple has 4 reserved')
  })

  it('takes stock of many SKUs and gives the variances', () => {
    const stock = inventory()
    const variances = stock.stockTake([
      { sku: 'apple', quantity: 8 },
      { sku: 'pear', quantity: 3 },
      { sku: 'fig', quantity: 2 },
    ])
    expect(variances).toEqual([
      { sku: 'apple', expected: 10, counted: 8, difference: -2 },
      { sku: 'fig', expected: 0, counted: 2, difference: 2 },
    ])
    expect(stock.level('fig').onHand).toBe(2)
  })

  it('changes nothing when one count of a stock take is wrong', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'pear', quantity: 2 }])
    expect(() =>
      stock.stockTake([
        { sku: 'apple', quantity: 1 },
        { sku: 'pear', quantity: 1 },
      ])
    ).toThrow('pear has 2 reserved')
    expect(() =>
      stock.stockTake([
        { sku: 'apple', quantity: 1 },
        { sku: 'apple', quantity: 2 },
      ])
    ).toThrow('SKU apple is counted more than once')
    expect(stock.level('apple').onHand).toBe(10)
  })
})

describe('movements', () => {
  it('logs the movements of a SKU', () => {
    const stock = inventory()
    stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
    stock.commit('order-1')
    stock.count('apple', 5)
    stock.writeOff('apple', 2)
    expect(stock.movements('apple')).toEqual([
      { sku: 'apple', quantity: 10, reason: 'received' },
      { sku: 'apple', quantity: -4, reason: 'shipped' },
      { sku: 'apple', quantity: -1, reason: 'counted' },
      { sku: 'apple', quantity: -2, reason: 'written-off' },
    ])
  })

  it('gives the history of a SKU with its running stock on hand', () => {
    const stock = inventory()
    stock.receive('apple', 2)
    stock.writeOff('apple', 5)
    expect(stock.history('apple').map((line) => line.balance)).toEqual([10, 12, 7])
  })

  it('lists the SKUs with low stock in SKU order', () => {
    const stock = inventory()
    stock.receive('fig', 1)
    stock.reserve('order-1', [{ sku: 'apple', quantity: 8 }])
    expect(stock.lowStock(4).map((level) => level.sku)).toEqual(['apple', 'fig', 'pear'])
    expect(stock.lowStock(2).map((level) => level.sku)).toEqual(['fig'])
  })
})
