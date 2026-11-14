// Customers and their accounts. A customer registers once, with a unique
// email address, and can keep a delivery address. Each customer has an
// account, which holds store credit (in cents) and loyalty points. The shop
// writes to customers through a Notifier, which is outside the shop.

import { check, checkNotEmpty } from './errors.ts'
import type { IsoDate } from './dates.ts'
import type { Cents } from './money.ts'

export interface Address {
  line1: string
  city: string
  postcode: string
  country: string // a two-letter country code, as `GB`
}

export interface Customer {
  id: string
  name: string
  email: string
  address?: Address
  registeredOn: IsoDate
  closedOn?: IsoDate // a closed customer can no longer place orders
}

export interface CustomerRepository {
  get(id: string): Customer | undefined
  save(customer: Customer): void
  list(): Customer[] // in the order that they registered
}

// One change to an account: store credit (in cents) or loyalty points.
export type EntryKind = 'credit' | 'points'

export interface AccountEntry {
  id: string
  customerId: string
  kind: EntryKind
  amount: number // added when above 0, taken when below
  reason: string
  on: IsoDate
}

export interface AccountRepository {
  add(entry: AccountEntry): void
  entries(customerId: string): AccountEntry[] // oldest first
}

// A balance of store credit and points, with each entry that made it.
export interface Statement {
  customerId: string
  credit: Cents
  points: number
  entries: AccountEntry[]
}

// A message to a customer.
export interface Message {
  to: string // an email address
  subject: string
  body: string
}

export interface Notifier {
  send(message: Message): void
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function normaliseEmail(email: string): string {
  return email.trim().toLowerCase()
}

export function checkEmail(email: string): void {
  check(EMAIL.test(normaliseEmail(email)), `${email} is not an email address`)
}

export function checkAddress(address: Address): void {
  checkNotEmpty(address.line1, 'address line')
  checkNotEmpty(address.city, 'city')
  checkNotEmpty(address.postcode, 'postcode')
  check(/^[A-Z]{2}$/.test(address.country), `${address.country} is not a country code`)
}

// The balance of one kind over the entries.
export function balanceOf(entries: readonly AccountEntry[], kind: EntryKind): number {
  return entries
    .filter((entry) => entry.kind === kind)
    .reduce((total, entry) => total + entry.amount, 0)
}

// A one-line address, as on a label: `1 High St, Leeds LS1 1AA, GB`.
export function formatAddress(address: Address): string {
  return `${address.line1}, ${address.city} ${address.postcode}, ${address.country}`
}

export function copyCustomer(customer: Customer): Customer {
  const copy: Customer = { ...customer }
  if (customer.address !== undefined) {
    copy.address = { ...customer.address }
  }
  return copy
}
