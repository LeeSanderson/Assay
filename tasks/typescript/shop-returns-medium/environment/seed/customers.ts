// Customers and their accounts: store credit and loyalty points.

export type {
  AccountEntry,
  AccountRepository,
  Address,
  Customer,
  CustomerRepository,
  EntryKind,
  Message,
  Notifier,
  Statement,
} from './domain/customer.ts'
export {
  InMemoryAccountRepository,
  InMemoryCustomerRepository,
  InMemoryOutbox,
} from './adapters/memory.ts'
export { statementText } from './adapters/text.ts'
export type { AccountsDeps } from './services/accounts.ts'
export { Accounts, CENTS_PER_POINT, POINTS_PER_REDEMPTION } from './services/accounts.ts'
export type { CustomersDeps } from './services/customers.ts'
export { Customers } from './services/customers.ts'
