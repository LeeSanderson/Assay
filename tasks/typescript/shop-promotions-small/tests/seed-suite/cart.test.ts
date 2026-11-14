import { expect, it } from '@jest/globals'
import { Cart } from './cart.ts'

it('starts empty', () => {
  const cart = new Cart()
  expect(cart.isEmpty()).toBe(true)
  expect(cart.lines()).toEqual([])
})

it('adds lines in the order that they were first added', () => {
  const cart = new Cart()
  cart.add('pear', 1)
  cart.add('apple', 2)
  expect(cart.lines()).toEqual([
    { sku: 'pear', quantity: 1 },
    { sku: 'apple', quantity: 2 },
  ])
})

it('adds to the quantity of a SKU that is in the cart', () => {
  const cart = new Cart()
  cart.add('apple', 2)
  cart.add('pear', 1)
  cart.add('apple', 3)
  expect(cart.lines()).toEqual([
    { sku: 'apple', quantity: 5 },
    { sku: 'pear', quantity: 1 },
  ])
})

it('rejects a quantity below 1', () => {
  const cart = new Cart()
  expect(() => cart.add('apple', 0)).toThrow('quantity must be at least 1')
  expect(cart.isEmpty()).toBe(true)
})

it('sets the quantity of a line', () => {
  const cart = new Cart()
  cart.add('apple', 2)
  cart.setQuantity('apple', 7)
  expect(cart.lines()).toEqual([{ sku: 'apple', quantity: 7 }])
  expect(() => cart.setQuantity('apple', 0)).toThrow('quantity must be at least 1')
})

it('removes a line', () => {
  const cart = new Cart()
  cart.add('apple', 2)
  cart.add('pear', 1)
  cart.remove('apple')
  expect(cart.lines()).toEqual([{ sku: 'pear', quantity: 1 }])
})

it('rejects a change to a SKU that is not in the cart', () => {
  const cart = new Cart()
  expect(() => cart.remove('kiwi')).toThrow('SKU kiwi is not in the cart')
  expect(() => cart.setQuantity('kiwi', 1)).toThrow('SKU kiwi is not in the cart')
})

it('counts the units and clears the cart', () => {
  const cart = new Cart()
  cart.add('apple', 2)
  cart.add('pear', 3)
  expect(cart.itemCount()).toBe(5)
  cart.clear()
  expect(cart.isEmpty()).toBe(true)
  expect(cart.itemCount()).toBe(0)
})
