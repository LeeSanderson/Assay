// Customers: the people who registered with the shop. Each has a unique
// email address (in any case) and can keep one delivery address.

import { checkAddress, checkEmail, normaliseEmail } from '../domain/customer.ts'
import type { Address, Customer, CustomerRepository } from '../domain/customer.ts'
import type { Clock } from '../domain/dates.ts'
import { checkNotEmpty, conflict, invalid, notFound, wrongState } from '../domain/errors.ts'
import { PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'

export interface CustomersDeps {
  repository: CustomerRepository
  clock: Clock
  ids: IdSource
}

export class Customers {
  constructor(private readonly deps: CustomersDeps) {}

  public register(name: string, email: string, address?: Address): Customer {
    checkNotEmpty(name, 'name')
    checkEmail(email)
    const normal = normaliseEmail(email)
    if (this.findByEmail(normal) !== undefined) {
      throw conflict(`email ${normal} is already registered`)
    }
    if (address !== undefined) {
      checkAddress(address)
    }
    const customer: Customer = {
      id: this.deps.ids.next(PREFIX.customer),
      name: name.trim(),
      email: normal,
      registeredOn: this.deps.clock.today(),
    }
    if (address !== undefined) {
      customer.address = { ...address }
    }
    this.deps.repository.save(customer)
    return customer
  }

  public customer(id: string): Customer {
    const customer = this.deps.repository.get(id)
    if (customer === undefined) {
      throw notFound('customer', id)
    }
    return customer
  }

  // The customer with the email address, in any case.
  public byEmail(email: string): Customer {
    const customer = this.findByEmail(normaliseEmail(email))
    if (customer === undefined) {
      throw notFound('customer', normaliseEmail(email))
    }
    return customer
  }

  public rename(id: string, name: string): Customer {
    checkNotEmpty(name, 'name')
    return this.change(id, (customer) => ({ ...customer, name: name.trim() }))
  }

  public changeEmail(id: string, email: string): Customer {
    checkEmail(email)
    const normal = normaliseEmail(email)
    const holder = this.findByEmail(normal)
    if (holder !== undefined && holder.id !== id) {
      throw conflict(`email ${normal} is already registered`)
    }
    return this.change(id, (customer) => ({ ...customer, email: normal }))
  }

  public moveTo(id: string, address: Address): Customer {
    checkAddress(address)
    return this.change(id, (customer) => ({ ...customer, address: { ...address } }))
  }

  // Closes the account of a customer, who keeps its orders but can place no
  // more of them.
  public close(id: string): Customer {
    const customer = this.open(id)
    return this.change(customer.id, (c) => ({ ...c, closedOn: this.deps.clock.today() }))
  }

  // The customer, if its account is open: `customer <id> is closed` if not.
  public open(id: string): Customer {
    const customer = this.customer(id)
    if (customer.closedOn !== undefined) {
      throw wrongState('customer', id, 'closed')
    }
    return customer
  }

  // The customers whose accounts are open, in the order that they registered.
  public openCustomers(): Customer[] {
    return this.deps.repository.list().filter((customer) => customer.closedOn === undefined)
  }

  // The delivery address of a customer: an error when it has none.
  public addressOf(id: string): Address {
    const customer = this.customer(id)
    if (customer.address === undefined) {
      throw invalid(`customer ${id} has no address`)
    }
    return customer.address
  }

  // The customers whose name or email holds the text, in any case, in the
  // order that they registered.
  public search(text: string): Customer[] {
    const wanted = text.toLowerCase()
    return this.deps.repository
      .list()
      .filter(
        (customer) =>
          customer.name.toLowerCase().includes(wanted) || customer.email.includes(wanted)
      )
  }

  private change(id: string, update: (customer: Customer) => Customer): Customer {
    const changed = update(this.customer(id))
    this.deps.repository.save(changed)
    return changed
  }

  private findByEmail(normal: string): Customer | undefined {
    return this.deps.repository.list().find((customer) => customer.email === normal)
  }
}
