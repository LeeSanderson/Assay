// Comma-separated values, for the reports: one header row of column names,
// then one row for each record. A value with a comma, a quote or a line
// break goes in quotes, with each quote doubled. Rows end with `\n`.

import { check } from '../domain/errors.ts'
import { formatCents } from '../domain/money.ts'
import type { ProductRow } from '../domain/product.ts'
import type { DailySales, PromotionUsage, StockValue } from '../domain/report.ts'

export type CsvValue = string | number

// A column of a table: its heading and how to read its value from a row.
export interface Column<T> {
  heading: string
  value: (row: T) => CsvValue
}

export function toCsv<T>(rows: readonly T[], columns: readonly Column<T>[]): string {
  const lines = [columns.map((column) => quote(column.heading)).join(',')]
  for (const row of rows) {
    lines.push(columns.map((column) => quote(String(column.value(row)))).join(','))
  }
  return lines.join('\n') + '\n'
}

// Reads CSV text back into rows of strings, the header row first.
export function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (char === '"') {
        quoted = false
      } else {
        field += char
      }
    } else if (char === '"') {
      quoted = true
    } else if (char === ',') {
      row.push(field)
      field = ''
    } else if (char === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else {
      field += char
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

// The rows of a price list in CSV, whose header row names the columns `sku`,
// `name` and `price`, in any order. A row with too few values gets empty ones.
export function productRows(text: string): ProductRow[] {
  const [header, ...rows] = parseCsv(text)
  const columns = (header ?? []).map((heading) => heading.trim().toLowerCase())
  for (const wanted of ['sku', 'name', 'price']) {
    check(columns.includes(wanted), `the price list has no ${wanted} column`)
  }
  const at = (row: string[], heading: string) => row[columns.indexOf(heading)] ?? ''
  return rows
    .filter((row) => row.some((value) => value.trim() !== ''))
    .map((row) => ({ sku: at(row, 'sku'), name: at(row, 'name'), price: at(row, 'price') }))
}

// The reports as CSV, amounts as units and hundredths.

export function dailySalesCsv(rows: readonly DailySales[]): string {
  return toCsv(rows, [
    { heading: 'date', value: (row) => row.date },
    { heading: 'orders', value: (row) => row.orders },
    { heading: 'revenue', value: (row) => formatCents(row.revenue) },
  ])
}

export function promotionUsageCsv(rows: readonly PromotionUsage[]): string {
  return toCsv(rows, [
    { heading: 'promotion', value: (row) => row.promotionId },
    { heading: 'orders', value: (row) => row.orders },
    { heading: 'amount', value: (row) => formatCents(row.amount) },
  ])
}

export function stockValuesCsv(rows: readonly StockValue[]): string {
  return toCsv(rows, [
    { heading: 'sku', value: (row) => row.sku },
    { heading: 'on hand', value: (row) => row.onHand },
    { heading: 'unit price', value: (row) => formatCents(row.unitPrice) },
    { heading: 'value', value: (row) => formatCents(row.value) },
  ])
}

function quote(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}
