// The errors of the shop. Every error that the shop throws on purpose is a
// ShopError, with a code that says what kind of error it is, and a message
// that says what went wrong in plain words. Callers match on the code; tests
// and people read the message.

export type ErrorCode =
  | 'not-found' // the thing that the caller named does not exist
  | 'invalid' // the input breaks a rule of the shop
  | 'conflict' // the thing already exists, or is already done
  | 'state' // the thing is in a state that does not allow the action
  | 'declined' // an outside service said no

export class ShopError extends Error {
  constructor(
    public readonly code: ErrorCode,
    message: string
  ) {
    super(message)
    this.name = 'ShopError'
  }
}

// `unknown <kind> <id>`, as in `unknown order order-9`.
export function notFound(kind: string, id: string): ShopError {
  return new ShopError('not-found', `unknown ${kind} ${id}`)
}

export function invalid(message: string): ShopError {
  return new ShopError('invalid', message)
}

export function conflict(message: string): ShopError {
  return new ShopError('conflict', message)
}

// `<kind> <id> is <state>`, as in `order order-1 is shipped`.
export function wrongState(kind: string, id: string, state: string): ShopError {
  return new ShopError('state', `${kind} ${id} is ${state}`)
}

export function declined(message: string): ShopError {
  return new ShopError('declined', message)
}

// Checks a rule of the shop: throws an `invalid` error when it does not hold.
export function check(rule: boolean, message: string): void {
  if (!rule) {
    throw invalid(message)
  }
}

// Checks a count of units, which every part of the shop requires to be a
// whole number of at least 1.
export function checkQuantity(quantity: number): void {
  check(Number.isInteger(quantity) && quantity >= 1, 'quantity must be at least 1')
}

// Checks that a name or a code holds more than spaces.
export function checkNotEmpty(text: string, what: string): void {
  check(text.trim() !== '', `${what} must not be empty`)
}

// Whether an error is a ShopError with the code.
export function isShopError(error: unknown, code?: ErrorCode): error is ShopError {
  return error instanceof ShopError && (code === undefined || error.code === code)
}
