package domain

import (
	"fmt"
	"strings"
	"testing"
)

func datesEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := datesShow(got), datesShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func datesShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func datesErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func datesMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestDates(t *testing.T) {
	t.Run("dates", func(t *testing.T) {
		t.Run("knows a real date in the form YYYY-MM-DD", func(t *testing.T) {
			datesEq(t, IsIsoDate("2026-03-10"), true)
			datesEq(t, IsIsoDate("2026-02-30"), false)
			datesEq(t, IsIsoDate("10/03/2026"), false)
		})

		t.Run("adds days across the end of a month and a year", func(t *testing.T) {
			datesEq(t, datesMust(AddDays("2026-03-10", 30))(t), "2026-04-09")
			datesEq(t, datesMust(AddDays("2026-12-31", 1))(t), "2027-01-01")
			datesEq(t, datesMust(AddDays("2026-03-01", -1))(t), "2026-02-28")
		})

		t.Run("counts the days between two dates", func(t *testing.T) {
			datesEq(t, DaysBetween("2026-03-10", "2026-04-09"), 30)
			datesEq(t, DaysBetween("2026-03-10", "2026-03-10"), 0)
			datesEq(t, DaysBetween("2026-03-10", "2026-03-01"), -9)
		})

		t.Run("rejects a text that is not a date", func(t *testing.T) {
			_, err := AddDays("soon", 1)
			datesErr(t, err, "soon is not a date")
		})
	})

	t.Run("periods", func(t *testing.T) {
		t.Run("holds both of its ends", func(t *testing.T) {
			datesEq(t, Within("2026-03-01", "2026-03-01", "2026-03-31"), true)
			datesEq(t, Within("2026-03-31", "2026-03-01", "2026-03-31"), true)
			datesEq(t, Within("2026-04-01", "2026-03-01", "2026-03-31"), false)
		})

		t.Run("rejects a period that ends before it starts", func(t *testing.T) {
			datesErr(t, CheckPeriod("2026-03-02", "2026-03-01"),
				"the period from 2026-03-02 to 2026-03-01 ends before it starts")
		})

		t.Run("lists each day of a period", func(t *testing.T) {
			datesEq(t, datesMust(EachDay("2026-02-27", "2026-03-02"))(t),
				[]IsoDate{"2026-02-27", "2026-02-28", "2026-03-01", "2026-03-02"})
		})
	})

	t.Run("months and weekdays", func(t *testing.T) {
		t.Run("gives the month of a date, and its first and last days", func(t *testing.T) {
			datesEq(t, MonthOf("2026-03-10"), "2026-03")
			datesEq(t, StartOfMonth("2026-03-10"), "2026-03-01")
			datesEq(t, EndOfMonth("2026-02-10"), "2026-02-28")
			datesEq(t, EndOfMonth("2028-02-10"), "2028-02-29")
			datesEq(t, EndOfMonth("2026-12-05"), "2026-12-31")
		})

		t.Run("names the day of the week", func(t *testing.T) {
			datesEq(t, Weekday("2026-03-10"), "Tuesday")
			datesEq(t, Weekday("2026-03-15"), "Sunday")
		})
	})
}
