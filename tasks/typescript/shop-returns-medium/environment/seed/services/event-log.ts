// The event log: what happened in the shop, oldest first. The recording
// stores (adapters/recording.ts) record each change; a part of the shop that
// wants to act on an event subscribes to its type. Subscribers run in the
// order that they subscribed, once the event is in the log.

import { checkPeriod, within } from '../domain/dates.ts'
import type { Clock, IsoDate } from '../domain/dates.ts'
import { checkNotEmpty } from '../domain/errors.ts'
import type { Change, ChangeSink, EventStore, ShopEvent } from '../domain/event.ts'
import { compareText, PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'

export interface EventLogDeps {
  store: EventStore
  clock: Clock
  ids: IdSource
}

export type Subscriber = (event: ShopEvent) => void

// How many events of a type the log holds.
export interface EventCount {
  type: string
  count: number
}

export class EventLog implements ChangeSink {
  private readonly subscribers: { type: string; subscriber: Subscriber }[] = []

  constructor(private readonly deps: EventLogDeps) {}

  public record(change: Change): ShopEvent {
    checkNotEmpty(change.type, 'event type')
    const event: ShopEvent = {
      id: this.deps.ids.next(PREFIX.event),
      type: change.type,
      subject: change.subject,
      on: this.deps.clock.today(),
      data: { ...change.data },
    }
    this.deps.store.append(event)
    for (const { type, subscriber } of this.subscribers) {
      if (type === event.type) {
        subscriber({ ...event, data: { ...event.data } })
      }
    }
    return event
  }

  public subscribe(type: string, subscriber: Subscriber): void {
    checkNotEmpty(type, 'event type')
    this.subscribers.push({ type, subscriber })
  }

  // Hands each event of the type that the log holds to the subscriber, oldest
  // first, as if it had subscribed from the start; it gives how many.
  public replay(type: string, subscriber: Subscriber): number {
    const events = this.ofType(type)
    for (const event of events) {
      subscriber(event)
    }
    return events.length
  }

  public all(): ShopEvent[] {
    return this.deps.store.list()
  }

  public ofType(type: string): ShopEvent[] {
    return this.all().filter((event) => event.type === type)
  }

  // The newest event of the type, if the log holds one.
  public lastOf(type: string): ShopEvent | undefined {
    const events = this.ofType(type)
    return events[events.length - 1]
  }

  // The events of one record, by its id.
  public about(subject: string): ShopEvent[] {
    return this.all().filter((event) => event.subject === subject)
  }

  public between(from: IsoDate, to: IsoDate): ShopEvent[] {
    checkPeriod(from, to)
    return this.all().filter((event) => within(event.on, from, to))
  }

  // The events after the one with the id, for a reader that has read up to it.
  public after(id: string): ShopEvent[] {
    const events = this.all()
    const index = events.findIndex((event) => event.id === id)
    return index === -1 ? events : events.slice(index + 1)
  }

  // The number of events of each type, by type.
  public counts(): EventCount[] {
    const counts = new Map<string, number>()
    for (const event of this.all()) {
      counts.set(event.type, (counts.get(event.type) ?? 0) + 1)
    }
    return [...counts.entries()]
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => compareText(a.type, b.type))
  }
}
