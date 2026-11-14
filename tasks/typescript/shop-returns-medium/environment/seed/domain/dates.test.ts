import { describe, expect, it } from '@jest/globals'
import {
  addDays,
  checkPeriod,
  daysBetween,
  eachDay,
  endOfMonth,
  isIsoDate,
  monthOf,
  startOfMonth,
  weekday,
  within,
} from './dates.ts'

describe('dates', () => {
  it('knows a real date in the form YYYY-MM-DD', () => {
    expect(isIsoDate('2026-03-10')).toBe(true)
    expect(isIsoDate('2026-02-30')).toBe(false)
    expect(isIsoDate('10/03/2026')).toBe(false)
  })

  it('adds days across the end of a month and a year', () => {
    expect(addDays('2026-03-10', 30)).toBe('2026-04-09')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
  })

  it('counts the days between two dates', () => {
    expect(daysBetween('2026-03-10', '2026-04-09')).toBe(30)
    expect(daysBetween('2026-03-10', '2026-03-10')).toBe(0)
    expect(daysBetween('2026-03-10', '2026-03-01')).toBe(-9)
  })

  it('rejects a text that is not a date', () => {
    expect(() => addDays('soon', 1)).toThrow('soon is not a date')
  })
})

describe('periods', () => {
  it('holds both of its ends', () => {
    expect(within('2026-03-01', '2026-03-01', '2026-03-31')).toBe(true)
    expect(within('2026-03-31', '2026-03-01', '2026-03-31')).toBe(true)
    expect(within('2026-04-01', '2026-03-01', '2026-03-31')).toBe(false)
  })

  it('rejects a period that ends before it starts', () => {
    expect(() => checkPeriod('2026-03-02', '2026-03-01')).toThrow(
      'the period from 2026-03-02 to 2026-03-01 ends before it starts'
    )
  })

  it('lists each day of a period', () => {
    expect(eachDay('2026-02-27', '2026-03-02')).toEqual([
      '2026-02-27',
      '2026-02-28',
      '2026-03-01',
      '2026-03-02',
    ])
  })
})

describe('months and weekdays', () => {
  it('gives the month of a date, and its first and last days', () => {
    expect(monthOf('2026-03-10')).toBe('2026-03')
    expect(startOfMonth('2026-03-10')).toBe('2026-03-01')
    expect(endOfMonth('2026-02-10')).toBe('2026-02-28')
    expect(endOfMonth('2028-02-10')).toBe('2028-02-29')
    expect(endOfMonth('2026-12-05')).toBe('2026-12-31')
  })

  it('names the day of the week', () => {
    expect(weekday('2026-03-10')).toBe('Tuesday')
    expect(weekday('2026-03-15')).toBe('Sunday')
  })
})
