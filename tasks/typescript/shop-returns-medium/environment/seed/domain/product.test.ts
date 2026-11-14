import { describe, expect, it } from '@jest/globals'
import { newProduct, productOfRow } from './product.ts'

describe('products', () => {
  it('makes a product that is on sale', () => {
    expect(newProduct('apple', 'Apple', 250)).toEqual({
      sku: 'apple',
      name: 'Apple',
      unitPrice: 250,
      discontinued: false,
    })
  })

  it('checks the SKU, then the name, then the price', () => {
    expect(() => newProduct('', '', 0)).toThrow('SKU must not be empty')
    expect(() => newProduct('apple', '', 0)).toThrow('name must not be empty')
    expect(() => newProduct('apple', 'Apple', 0)).toThrow('unit price must be at least 1')
    expect(() => newProduct('apple', 'Apple', 2.5)).toThrow(
      'unit price must be a whole number of cents'
    )
  })

  it('reads a product from a row of a price list', () => {
    expect(productOfRow({ sku: ' fig ', name: 'Fig ', price: '4.20' })).toEqual({
      sku: 'fig',
      name: 'Fig',
      unitPrice: 420,
      discontinued: false,
    })
    expect(() => productOfRow({ sku: 'fig', name: 'Fig', price: 'cheap' })).toThrow(
      'cheap is not an amount'
    )
  })
})
