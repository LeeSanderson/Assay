// The date and the identifiers that the shop uses, behind interfaces so that
// the tests can fix them.

export interface Clock {
  today(): string
}

// A clock that stays on one date until it is set to another. Dates are
// strings in the form YYYY-MM-DD.
export class FixedClock implements Clock {
  constructor(private date: string) {}

  today(): string {
    return this.date
  }

  set(date: string): void {
    this.date = date
  }
}

export interface IdSource {
  next(prefix: string): string
}

// Gives `<prefix>-1`, `<prefix>-2` and so on, with one count for each prefix.
export class SequentialIds implements IdSource {
  private readonly counts = new Map<string, number>()

  next(prefix: string): string {
    const count = (this.counts.get(prefix) ?? 0) + 1
    this.counts.set(prefix, count)
    return `${prefix}-${count}`
  }
}
