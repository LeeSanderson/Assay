// The date and the identifiers that the shop uses, behind interfaces so that
// the tests can fix them.

export type { Clock, IsoDate } from './domain/dates.ts'
export type { IdSource } from './domain/ids.ts'
export { FixedClock, SequentialIds } from './adapters/clock.ts'
