import { expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from './clock.ts'

it('a fixed clock gives its date until it is set', () => {
  const clock = new FixedClock('2026-03-10')
  expect(clock.today()).toBe('2026-03-10')
  clock.set('2026-03-11')
  expect(clock.today()).toBe('2026-03-11')
})

it('sequential ids count from 1 for each prefix', () => {
  const ids = new SequentialIds()
  expect([ids.next('order'), ids.next('order'), ids.next('payment')]).toEqual([
    'order-1',
    'order-2',
    'payment-1',
  ])
})
