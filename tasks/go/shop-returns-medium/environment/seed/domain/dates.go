// Dates. The shop works in whole days, held as strings in the form
// YYYY-MM-DD, so that two dates compare as strings. The date of today comes
// from a Clock, never from the system.

package domain

import (
	"fmt"
	"time"
)

type IsoDate = string

type Clock interface {
	Today() IsoDate
}

const layout = "2006-01-02"

func parse(date IsoDate) time.Time {
	t, _ := time.Parse(layout, date)
	return t
}

func IsIsoDate(text string) bool {
	_, err := time.Parse(layout, text)
	return err == nil
}

func CheckDate(text string) error {
	return Check(IsIsoDate(text), text+" is not a date")
}

// AddDays gives the date `days` days after the date (before it, when `days`
// is below 0).
func AddDays(date IsoDate, days int) (IsoDate, error) {
	if err := CheckDate(date); err != nil {
		return "", err
	}
	return parse(date).AddDate(0, 0, days).Format(layout), nil
}

// DaysBetween gives the number of days from one date to another: 1 from one
// day to the next. The dates of the records are valid, so it checks none.
func DaysBetween(from, to IsoDate) int {
	return int(parse(to).Sub(parse(from)).Hours() / 24)
}

// Within tells whether the date is in the period from `from` to `to`, both
// included.
func Within(date, from, to IsoDate) bool { return date >= from && date <= to }

// CheckPeriod checks a period: two dates, the first not after the second.
func CheckPeriod(from, to IsoDate) error {
	return first(CheckDate(from), CheckDate(to),
		Check(from <= to, fmt.Sprintf("the period from %s to %s ends before it starts", from, to)))
}

// MonthOf gives the month of a date: `2026-03` for `2026-03-10`. Like the
// other helpers below, it takes a valid date.
func MonthOf(date IsoDate) string { return parse(date).Format("2006-01") }

func StartOfMonth(date IsoDate) IsoDate { return MonthOf(date) + "-01" }

// EndOfMonth gives the last day of the month of the date.
func EndOfMonth(date IsoDate) IsoDate {
	return parse(StartOfMonth(date)).AddDate(0, 1, -1).Format(layout)
}

// Weekday names the day of the week of the date.
func Weekday(date IsoDate) string { return parse(date).Weekday().String() }

// EachDay gives each date from `from` to `to`, both included.
func EachDay(from, to IsoDate) ([]IsoDate, error) {
	if err := CheckPeriod(from, to); err != nil {
		return nil, err
	}
	var days []IsoDate
	for day := parse(from); day.Format(layout) <= to; day = day.AddDate(0, 0, 1) {
		days = append(days, day.Format(layout))
	}
	return days, nil
}

// Latest gives the later of two dates.
func Latest(a, b IsoDate) IsoDate { return max(a, b) }
