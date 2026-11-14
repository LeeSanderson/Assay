// Identifiers. Every record that the shop creates gets its id from an
// IdSource, as `<prefix>-<n>`: `order-1`, `payment-3`. The prefix names the
// kind of record; each kind has its own count. A product is the one record
// whose id the shop does not make: its SKU, which the caller gives.

export interface IdSource {
  next(prefix: string): string
}

// The prefix of each kind of record that the shop numbers.
export const PREFIX = {
  order: 'order',
  payment: 'payment',
  customer: 'customer',
  shipment: 'shipment',
  invoice: 'invoice',
  event: 'event',
  entry: 'entry',
  supplier: 'supplier',
  purchase: 'purchase',
  credit: 'credit',
} as const

// The number at the end of an id, or 0 when the id has none: `order-12` is 12.
export function idNumber(id: string): number {
  const match = /-(\d+)$/.exec(id)
  return match === null ? 0 : Number(match[1])
}

// Orders ids of one kind by their number, so that `order-10` comes after
// `order-9`; ids of different kinds by their prefix.
export function compareIds(a: string, b: string): number {
  const prefixA = a.replace(/-\d+$/, '')
  const prefixB = b.replace(/-\d+$/, '')
  if (prefixA !== prefixB) {
    return prefixA < prefixB ? -1 : 1
  }
  return idNumber(a) - idNumber(b)
}

// Orders two texts as the shop sorts SKUs and codes: by their UTF-16 units.
export function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}
