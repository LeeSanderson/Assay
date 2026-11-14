import { describe, expect, it } from '@jest/globals'
import { dailySalesCsv, parseCsv, productRows, stockValuesCsv, toCsv } from './csv.ts'

describe('csv', () => {
  it('writes a header row and one row for each record', () => {
    const rows = [
      { sku: 'apple', units: 2 },
      { sku: 'pear', units: 1 },
    ]
    expect(
      toCsv(rows, [
        { heading: 'sku', value: (row) => row.sku },
        { heading: 'units', value: (row) => row.units },
      ])
    ).toBe('sku,units\napple,2\npear,1\n')
  })

  it('quotes a value with a comma, a quote or a line break', () => {
    const rows = [{ name: 'Apples, "red"' }]
    expect(toCsv(rows, [{ heading: 'name', value: (row) => row.name }])).toBe(
      'name\n"Apples, ""red"""\n'
    )
  })

  it('reads quoted values back', () => {
    expect(parseCsv('name,price\n"Apples, ""red""",2.50\nPear,10.00\n')).toEqual([
      ['name', 'price'],
      ['Apples, "red"', '2.50'],
      ['Pear', '10.00'],
    ])
  })

  it('writes reports with amounts in units and hundredths', () => {
    expect(dailySalesCsv([{ date: '2026-03-10', orders: 2, revenue: 1350 }])).toBe(
      'date,orders,revenue\n2026-03-10,2,13.50\n'
    )
    expect(stockValuesCsv([{ sku: 'apple', onHand: 4, unitPrice: 250, value: 1000 }])).toBe(
      'sku,on hand,unit price,value\napple,4,2.50,10.00\n'
    )
  })
})

describe('price lists', () => {
  it('reads the rows of a price list by the names of its columns', () => {
    expect(productRows('price,sku,name\n2.50,apple,Apple\n\n10.00,pear,Pear\n')).toEqual([
      { sku: 'apple', name: 'Apple', price: '2.50' },
      { sku: 'pear', name: 'Pear', price: '10.00' },
    ])
  })

  it('rejects a price list without a column that it needs', () => {
    expect(() => productRows('sku,name\napple,Apple\n')).toThrow(
      'the price list has no price column'
    )
  })
})
