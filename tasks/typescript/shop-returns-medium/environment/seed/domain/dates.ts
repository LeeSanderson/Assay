// Dates. The shop works in whole days, held as strings in the form
// YYYY-MM-DD, so that two dates compare as strings. The date of today comes
// from a Clock, never from the system.

import { check } from './errors.ts'

export type IsoDate = string

export interface Clock {
  today(): IsoDate
}

const DAY_MS = 24 * 60 * 60 * 1000

export function isIsoDate(text: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return false
  }
  const time = Date.parse(`${text}T00:00:00Z`)
  return !Number.isNaN(time) && new Date(time).toISOString().slice(0, 10) === text
}

export function checkDate(text: string): void {
  check(isIsoDate(text), `${text} is not a date`)
}

// The date `days` days after the date (before it, when `days` is negative).
export function addDays(date: IsoDate, days: number): IsoDate {
  checkDate(date)
  const time = Date.parse(`${date}T00:00:00Z`) + days * DAY_MS
  return new Date(time).toISOString().slice(0, 10)
}

// The number of days from `from` to `to`: 1 from one day to the next.
export function daysBetween(from: IsoDate, to: IsoDate): number {
  checkDate(from)
  checkDate(to)
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS)
}

// Whether the date is in the period from `from` to `to`, both included.
export function within(date: IsoDate, from: IsoDate, to: IsoDate): boolean {
  return date >= from && date <= to
}

// Checks a period: two dates, the first not after the second.
export function checkPeriod(from: IsoDate, to: IsoDate): void {
  checkDate(from)
  checkDate(to)
  check(from <= to, `the period from ${from} to ${to} ends before it starts`)
}

// The month of a date: `2026-03` for `2026-03-10`.
export function monthOf(date: IsoDate): string {
  checkDate(date)
  return date.slice(0, 7)
}

export function startOfMonth(date: IsoDate): IsoDate {
  return `${monthOf(date)}-01`
}

// The last day of the month of the date.
export function endOfMonth(date: IsoDate): IsoDate {
  const [year, month] = monthOf(date).split('-').map(Number)
  const next = month === 12 ? `${year + 1}-01-01` : `${year}-${pad(month + 1)}-01`
  return addDays(next, -1)
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

// The name of the day of the week of the date.
export function weekday(date: IsoDate): string {
  checkDate(date)
  return WEEKDAYS[new Date(`${date}T00:00:00Z`).getUTCDay()]
}

// Each date from `from` to `to`, both included.
export function eachDay(from: IsoDate, to: IsoDate): IsoDate[] {
  checkPeriod(from, to)
  const days: IsoDate[] = []
  for (let day = from; day <= to; day = addDays(day, 1)) {
    days.push(day)
  }
  return days
}

// The later of two dates.
export function latest(a: IsoDate, b: IsoDate): IsoDate {
  return a > b ? a : b
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}
