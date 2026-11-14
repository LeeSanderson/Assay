import { expect, it } from '@jest/globals'
import { InMemoryStockRepository, Inventory } from './inventory.ts'

function inventory(): Inventory {
  const stock = new Inventory(new InMemoryStockRepository())
  stock.receive('apple', 10)
  stock.receive('pear', 3)
  return stock
}

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

it('counts stock but not below the reserved stock', () => {
  const stock = inventory()
  stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
  stock.count('apple', 7)
  expect(stock.level('apple')).toEqual({ sku: 'apple', onHand: 7, reserved: 4 })
  expect(() => stock.count('apple', 3)).toThrow('apple has 4 reserved')
})

it('logs the movements of a SKU', () => {
  const stock = inventory()
  stock.reserve('order-1', [{ sku: 'apple', quantity: 4 }])
  stock.commit('order-1')
  stock.count('apple', 5)
  expect(stock.movements('apple')).toEqual([
    { sku: 'apple', quantity: 10, reason: 'received' },
    { sku: 'apple', quantity: -4, reason: 'shipped' },
    { sku: 'apple', quantity: -1, reason: 'counted' },
  ])
})

it('lists the SKUs with low stock in SKU order', () => {
  const stock = inventory()
  stock.receive('fig', 1)
  stock.reserve('order-1', [{ sku: 'apple', quantity: 8 }])
  expect(stock.lowStock(4).map((level) => level.sku)).toEqual(['apple', 'fig', 'pear'])
  expect(stock.lowStock(2).map((level) => level.sku)).toEqual(['fig'])
})
