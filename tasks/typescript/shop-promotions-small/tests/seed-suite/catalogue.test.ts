import { expect, it } from '@jest/globals'
import { Catalogue, InMemoryProductRepository } from './catalogue.ts'

function catalogue(): Catalogue {
  return new Catalogue(new InMemoryProductRepository())
}

it('adds a product that is on sale', () => {
  const shop = catalogue()
  expect(shop.addProduct('apple', 'Apple', 250)).toEqual({
    sku: 'apple',
    name: 'Apple',
    unitPrice: 250,
    discontinued: false,
  })
  expect(shop.product('apple').unitPrice).toBe(250)
})

it('rejects a product with an empty SKU', () => {
  expect(() => catalogue().addProduct(' ', 'Apple', 250)).toThrow('SKU must not be empty')
})

it('rejects a product with an empty name', () => {
  expect(() => catalogue().addProduct('apple', '', 250)).toThrow('name must not be empty')
})

it('rejects a unit price below 1', () => {
  expect(() => catalogue().addProduct('apple', 'Apple', 0)).toThrow(
    'unit price must be at least 1'
  )
})

it('rejects a SKU that already exists', () => {
  const shop = catalogue()
  shop.addProduct('apple', 'Apple', 250)
  expect(() => shop.addProduct('apple', 'Green apple', 300)).toThrow(
    'product apple already exists'
  )
  expect(shop.product('apple').name).toBe('Apple')
})

it('rejects an unknown product', () => {
  expect(() => catalogue().product('kiwi')).toThrow('unknown product kiwi')
})

it('changes the price of a product', () => {
  const shop = catalogue()
  shop.addProduct('apple', 'Apple', 250)
  shop.changePrice('apple', 275)
  expect(shop.product('apple').unitPrice).toBe(275)
  expect(() => shop.changePrice('apple', 0)).toThrow('unit price must be at least 1')
})

it('renames a product', () => {
  const shop = catalogue()
  shop.addProduct('apple', 'Apple', 250)
  shop.rename('apple', 'Red apple')
  expect(shop.product('apple').name).toBe('Red apple')
  expect(() => shop.rename('apple', '')).toThrow('name must not be empty')
})

it('lists the products on sale in SKU order without the discontinued ones', () => {
  const shop = catalogue()
  shop.addProduct('pear', 'Pear', 1000)
  shop.addProduct('apple', 'Apple', 250)
  shop.addProduct('fig', 'Fig', 400)
  shop.discontinue('fig')
  expect(shop.activeProducts().map((product) => product.sku)).toEqual(['apple', 'pear'])
  expect(shop.product('fig').discontinued).toBe(true)
})

it('searches the names of the products on sale in any case', () => {
  const shop = catalogue()
  shop.addProduct('apple', 'Apple', 250)
  shop.addProduct('crab', 'Crab apple', 90)
  shop.addProduct('pear', 'Pear', 1000)
  expect(shop.search('APPLE').map((product) => product.sku)).toEqual(['apple', 'crab'])
})
