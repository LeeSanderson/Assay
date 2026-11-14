import { describe, expect, it } from '@jest/globals'
import {
  check,
  checkNotEmpty,
  checkQuantity,
  isShopError,
  notFound,
  ShopError,
  wrongState,
} from './errors.ts'

describe('shop errors', () => {
  it('names an unknown record by its kind and id', () => {
    const error = notFound('order', 'order-9')
    expect(error).toBeInstanceOf(ShopError)
    expect(error).toBeInstanceOf(Error)
    expect([error.code, error.message]).toEqual(['not-found', 'unknown order order-9'])
  })

  it('names a record in the wrong state', () => {
    const error = wrongState('order', 'order-1', 'shipped')
    expect([error.code, error.message]).toEqual(['state', 'order order-1 is shipped'])
  })

  it('tells a shop error by its code', () => {
    expect(isShopError(notFound('order', 'x'), 'not-found')).toBe(true)
    expect(isShopError(notFound('order', 'x'), 'state')).toBe(false)
    expect(isShopError(new Error('boom'))).toBe(false)
  })
})

describe('checks', () => {
  it('throws an invalid error when a rule does not hold', () => {
    expect(() => check(false, 'no')).toThrow('no')
    expect(() => check(true, 'no')).not.toThrow()
  })

  it('rejects a quantity that is not a whole number of at least 1', () => {
    for (const quantity of [0, -1, 1.5]) {
      expect(() => checkQuantity(quantity)).toThrow('quantity must be at least 1')
    }
    expect(() => checkQuantity(1)).not.toThrow()
  })

  it('rejects text that holds only spaces', () => {
    expect(() => checkNotEmpty('  ', 'name')).toThrow('name must not be empty')
  })
})
