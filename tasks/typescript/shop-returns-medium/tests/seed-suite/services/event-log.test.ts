import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import { InMemoryEventStore } from '../adapters/memory.ts'
import type { ShopEvent } from '../domain/event.ts'
import { EventLog } from './event-log.ts'

function log() {
  const clock = new FixedClock('2026-03-10')
  const events = new EventLog({ store: new InMemoryEventStore(), clock, ids: new SequentialIds() })
  return { clock, events }
}

describe('recording', () => {
  it('records a change as an event with an id and the date', () => {
    const { events } = log()
    const event = events.record({ type: 'order-placed', subject: 'order-1', data: { total: 5 } })
    expect(event).toEqual({
      id: 'event-1',
      type: 'order-placed',
      subject: 'order-1',
      on: '2026-03-10',
      data: { total: 5 },
    })
    expect(events.all()).toEqual([event])
  })

  it('rejects an event with no type', () => {
    const { events } = log()
    expect(() => events.record({ type: '', subject: 'x', data: {} })).toThrow(
      'event type must not be empty'
    )
  })
})

describe('reading', () => {
  it('finds the events by type, by record and by period', () => {
    const { clock, events } = log()
    events.record({ type: 'order-placed', subject: 'order-1', data: {} })
    clock.set('2026-03-12')
    events.record({ type: 'order-shipped', subject: 'order-1', data: {} })
    events.record({ type: 'order-placed', subject: 'order-2', data: {} })
    expect(events.ofType('order-placed').map((e) => e.subject)).toEqual(['order-1', 'order-2'])
    expect(events.about('order-1').map((e) => e.type)).toEqual(['order-placed', 'order-shipped'])
    expect(events.between('2026-03-11', '2026-03-31').map((e) => e.id)).toEqual([
      'event-2',
      'event-3',
    ])
    expect(events.lastOf('order-placed')?.subject).toBe('order-2')
    expect(events.lastOf('invoice-issued')).toBeUndefined()
  })

  it('gives the events after one that a reader has read', () => {
    const { events } = log()
    for (const subject of ['a', 'b', 'c']) events.record({ type: 't', subject, data: {} })
    expect(events.after('event-1').map((e) => e.subject)).toEqual(['b', 'c'])
    expect(events.after('event-9')).toHaveLength(3)
  })

  it('counts the events of each type, by type', () => {
    const { events } = log()
    events.record({ type: 'order-shipped', subject: 'o', data: {} })
    events.record({ type: 'order-placed', subject: 'o', data: {} })
    events.record({ type: 'order-placed', subject: 'p', data: {} })
    expect(events.counts()).toEqual([
      { type: 'order-placed', count: 2 },
      { type: 'order-shipped', count: 1 },
    ])
  })
})

describe('subscribers', () => {
  it('hands each new event of its type to each subscriber, in the order that they subscribed', () => {
    const { events } = log()
    const seen: string[] = []
    events.subscribe('order-placed', (event) => seen.push(`first ${event.subject}`))
    events.subscribe('order-placed', (event) => seen.push(`second ${event.subject}`))
    events.subscribe('order-shipped', (event) => seen.push(`shipped ${event.subject}`))
    events.record({ type: 'order-placed', subject: 'order-1', data: {} })
    expect(seen).toEqual(['first order-1', 'second order-1'])
  })

  it('has the event in the log before a subscriber runs', () => {
    const { events } = log()
    let held = 0
    events.subscribe('order-placed', () => {
      held = events.all().length
    })
    events.record({ type: 'order-placed', subject: 'order-1', data: {} })
    expect(held).toBe(1)
  })

  it('replays the events of a type to a new subscriber', () => {
    const { events } = log()
    events.record({ type: 'order-placed', subject: 'order-1', data: {} })
    events.record({ type: 'order-shipped', subject: 'order-1', data: {} })
    events.record({ type: 'order-placed', subject: 'order-2', data: {} })
    const seen: ShopEvent[] = []
    expect(events.replay('order-placed', (event) => seen.push(event))).toBe(2)
    expect(seen.map((event) => event.subject)).toEqual(['order-1', 'order-2'])
  })
})
