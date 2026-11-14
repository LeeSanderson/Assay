// The clock and the identifiers of the shop in memory, so that the tests and
// the shop's users can fix them.

import { addDays } from '../domain/dates.ts'
import type { Clock, IsoDate } from '../domain/dates.ts'
import type { IdSource } from '../domain/ids.ts'

// A clock that stays on one date until it is set to another. Dates are
// strings in the form YYYY-MM-DD.
export class FixedClock implements Clock {
  constructor(private date: IsoDate) {}

  today(): IsoDate {
    return this.date
  }

  set(date: IsoDate): void {
    this.date = date
  }

  // Moves the clock on by whole days.
  advance(days: number): void {
    this.date = addDays(this.date, days)
  }
}

// Gives `<prefix>-1`, `<prefix>-2` and so on, with one count for each prefix.
export class SequentialIds implements IdSource {
  private readonly counts = new Map<string, number>()

  next(prefix: string): string {
    const count = (this.counts.get(prefix) ?? 0) + 1
    this.counts.set(prefix, count)
    return `${prefix}-${count}`
  }

  // How many ids of the prefix it has given.
  given(prefix: string): number {
    return this.counts.get(prefix) ?? 0
  }
}
