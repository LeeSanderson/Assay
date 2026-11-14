import { expect, it } from '@jest/globals'
import { normalise } from './names.ts'

it('trims a name', () => {
  expect(normalise('  apple ')).toBe('apple')
})

it('puts a name in lower case', () => {
  expect(normalise('Apple')).toBe('apple')
})
