// A product of the catalogue: what the shop sells, under its SKU, at a unit
// price in cents. A discontinued product stays in the catalogue, but is no
// longer on sale.

import { check, checkNotEmpty } from './errors.ts'
import { parseCents } from './money.ts'
import type { Cents } from './money.ts'

export interface Product {
  sku: string
  name: string
  unitPrice: Cents
  discontinued: boolean
}

// A change of the price of a product.
export interface PriceChange {
  sku: string
  from: Cents
  to: Cents
}

export interface ProductRepository {
  get(sku: string): Product | undefined
  save(product: Product): void
  list(): Product[]
}

export function checkSku(sku: string): void {
  checkNotEmpty(sku, 'SKU')
}

export function checkName(name: string): void {
  checkNotEmpty(name, 'name')
}

export function checkPrice(unitPrice: Cents): void {
  check(unitPrice >= 1, 'unit price must be at least 1')
  check(Number.isInteger(unitPrice), 'unit price must be a whole number of cents')
}

export function newProduct(sku: string, name: string, unitPrice: Cents): Product {
  checkSku(sku)
  checkName(name)
  checkPrice(unitPrice)
  return { sku, name, unitPrice, discontinued: false }
}

// One row of a price list, as a supplier sends it: the price as text, in
// units and hundredths.
export interface ProductRow {
  sku: string
  name: string
  price: string
}

// What an import of a price list did: the SKUs that it added and those whose
// name or price it changed, in the order of the rows, and each row that it
// rejected, by its number (the first row is 1), with the reason.
export interface ImportResult {
  added: string[]
  updated: string[]
  rejected: { row: number; reason: string }[]
}

// The product that a row describes, or the error of its first broken rule.
export function productOfRow(row: ProductRow): Product {
  return newProduct(row.sku.trim(), row.name.trim(), parseCents(row.price))
}

export function copyProduct(product: Product): Product {
  return { ...product }
}
