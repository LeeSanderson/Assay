import { describe, expect, it } from '@jest/globals'
import { InMemoryProductRepository } from '../adapters/memory.ts'
import { Catalogue } from './catalogue.ts'

function catalogue(): Catalogue {
  return new Catalogue(new InMemoryProductRepository())
}

describe('products', () => {
  it('adds a product that is on sale', () => {
    const shop = catalogue()
    expect(shop.addProduct('apple', 'Apple', 250)).toEqual({
      sku: 'apple',
      name: 'Apple',
      unitPrice: 250,
      discontinued: false,
    })
    expect(shop.product('apple').unitPrice).toBe(250)
    expect([shop.has('apple'), shop.has('kiwi')]).toEqual([true, false])
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

  it('renames a product', () => {
    const shop = catalogue()
    shop.addProduct('apple', 'Apple', 250)
    shop.rename('apple', 'Red apple')
    expect(shop.product('apple').name).toBe('Red apple')
    expect(() => shop.rename('apple', '')).toThrow('name must not be empty')
  })
})

describe('prices', () => {
  it('changes the price of a product', () => {
    const shop = catalogue()
    shop.addProduct('apple', 'Apple', 250)
    shop.changePrice('apple', 275)
    expect(shop.product('apple').unitPrice).toBe(275)
    expect(() => shop.changePrice('apple', 0)).toThrow('unit price must be at least 1')
  })

  it('keeps the history of the prices of a product', () => {
    const shop = catalogue()
    shop.addProduct('apple', 'Apple', 250)
    shop.changePrice('apple', 275)
    shop.changePrice('apple', 275)
    shop.changePrice('apple', 260)
    expect(shop.priceHistory('apple')).toEqual([
      { sku: 'apple', from: 250, to: 275 },
      { sku: 'apple', from: 275, to: 260 },
    ])
  })

  it('reprices the products on sale by a percentage, rounded down', () => {
    const shop = catalogue()
    shop.addProduct('apple', 'Apple', 250)
    shop.addProduct('pear', 'Pear', 999)
    shop.addProduct('fig', 'Fig', 400)
    shop.discontinue('fig')
    expect(shop.reprice(10).map((p) => [p.sku, p.unitPrice])).toEqual([
      ['apple', 275],
      ['pear', 1098],
    ])
    expect(shop.product('fig').unitPrice).toBe(400)
    expect(shop.reprice(-50, ['apple']).map((p) => p.unitPrice)).toEqual([137])
  })

  it('never reprices a product below 1 cent', () => {
    const shop = catalogue()
    shop.addProduct('pin', 'Pin', 1)
    shop.addProduct('nail', 'Nail', 3)
    expect(shop.reprice(-90).map((p) => [p.sku, p.unitPrice])).toEqual([['nail', 1]])
  })

  it('finds the products on sale in a price range, cheapest first', () => {
    const shop = catalogue()
    shop.addProduct('pear', 'Pear', 1000)
    shop.addProduct('apple', 'Apple', 250)
    shop.addProduct('crab', 'Crab apple', 250)
    shop.addProduct('fig', 'Fig', 400)
    expect(shop.inPriceRange(250, 400).map((p) => p.sku)).toEqual(['apple', 'crab', 'fig'])
  })
})

describe('the range on sale', () => {
  it('lists the products on sale in SKU order without the discontinued ones', () => {
    const shop = catalogue()
    shop.addProduct('pear', 'Pear', 1000)
    shop.addProduct('apple', 'Apple', 250)
    shop.addProduct('fig', 'Fig', 400)
    shop.discontinue('fig')
    expect(shop.activeProducts().map((product) => product.sku)).toEqual(['apple', 'pear'])
    expect(shop.product('fig').discontinued).toBe(true)
  })

  it('puts a discontinued product back on sale', () => {
    const shop = catalogue()
    shop.addProduct('fig', 'Fig', 400)
    shop.discontinue('fig')
    shop.reinstate('fig')
    expect(shop.activeProducts().map((product) => product.sku)).toEqual(['fig'])
  })

  it('searches the names of the products on sale in any case', () => {
    const shop = catalogue()
    shop.addProduct('apple', 'Apple', 250)
    shop.addProduct('crab', 'Crab apple', 90)
    shop.addProduct('pear', 'Pear', 1000)
    expect(shop.search('APPLE').map((product) => product.sku)).toEqual(['apple', 'crab'])
  })
})

describe('price lists', () => {
  it('adds the new products and updates the known ones', () => {
    const shop = catalogue()
    shop.addProduct('apple', 'Apple', 250)
    shop.addProduct('pear', 'Pear', 1000)
    const result = shop.importProducts([
      { sku: 'fig', name: 'Fig', price: '4.00' },
      { sku: 'apple', name: 'Apple', price: '2.75' },
      { sku: 'pear', name: 'Pear', price: '10.00' },
    ])
    expect(result).toEqual({ added: ['fig'], updated: ['apple'], rejected: [] })
    expect(shop.product('apple').unitPrice).toBe(275)
    expect(shop.priceHistory('apple')).toEqual([{ sku: 'apple', from: 250, to: 275 }])
  })

  it('rejects each broken row by its number and imports the rest', () => {
    const shop = catalogue()
    const result = shop.importProducts([
      { sku: 'fig', name: 'Fig', price: '4.00' },
      { sku: '', name: 'Nothing', price: '1.00' },
      { sku: 'kiwi', name: 'Kiwi', price: 'free' },
      { sku: 'fig', name: 'Fig again', price: '5.00' },
    ])
    expect(result).toEqual({
      added: ['fig'],
      updated: [],
      rejected: [
        { row: 2, reason: 'SKU must not be empty' },
        { row: 3, reason: 'free is not an amount' },
        { row: 4, reason: 'SKU fig is on more than one row' },
      ],
    })
    expect(shop.product('fig').name).toBe('Fig')
  })
})
