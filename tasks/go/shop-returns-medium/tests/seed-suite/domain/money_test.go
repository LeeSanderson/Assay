package domain

import (
	"fmt"
	"strings"
	"testing"
)

func monEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := monShow(got), monShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func monShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func monErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func monMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestMoney(t *testing.T) {
	t.Run("arithmetic", func(t *testing.T) {
		t.Run("adds amounts and prices units", func(t *testing.T) {
			monEq(t, Sum([]Cents{250, 1000, 5}), 1255)
			monEq(t, Sum(nil), 0)
			monEq(t, Times(250, 4), 1000)
		})

		t.Run("takes a percentage and rounds it down", func(t *testing.T) {
			monEq(t, PercentOf(1000, 10), 100)
			monEq(t, PercentOf(750, 15), 112)
			monEq(t, PercentOf(99, 50), 49)
		})

		t.Run("takes a share of an amount and rounds it down", func(t *testing.T) {
			monEq(t, monMust(ShareOf(112, 1, 3))(t), 37)
			monEq(t, monMust(ShareOf(112, 2, 3))(t), 74)
			monEq(t, monMust(ShareOf(112, 3, 3))(t), 112)
			_, err := ShareOf(100, 1, 0)
			monErr(t, err, "a share needs a whole above 0")
		})

		t.Run("rejects an amount that is not a whole number of cents", func(t *testing.T) {
			// Go amounts are ints, so only the least amount can be broken.
			monErr(t, CheckCents(0, "amount", 1), "amount must be at least 1")
			if err := CheckCents(0, "amount", 0); err != nil {
				t.Fatal(err)
			}
		})
	})

	t.Run("allocation", func(t *testing.T) {
		t.Run("splits an amount in proportion and gives the rounding to the first parts", func(t *testing.T) {
			monEq(t, Allocate(100, []int{1, 1, 1}), []Cents{34, 33, 33})
			monEq(t, Allocate(1000, []int{250, 750}), []Cents{250, 750})
			monEq(t, Allocate(10, []int{1, 2}), []Cents{4, 6})
		})

		t.Run("gives nothing to a weight of zero", func(t *testing.T) {
			monEq(t, Allocate(5, []int{0, 1, 1}), []Cents{0, 3, 2})
			monEq(t, Allocate(5, []int{0, 0}), []Cents{0, 0})
		})

		t.Run("splits an amount evenly", func(t *testing.T) {
			monEq(t, monMust(SplitEvenly(100, 3))(t), []Cents{34, 33, 33})
			monEq(t, monMust(SplitEvenly(7, 1))(t), []Cents{7})
			_, err := SplitEvenly(7, 0)
			monErr(t, err, "parts must be at least 1")
		})

		t.Run("takes an amount from the lines in order, up to what each has left", func(t *testing.T) {
			remaining := []Cents{250, 1000, 400}
			monEq(t, TakeInOrder(remaining, []int{0, 1}, 300), 300)
			monEq(t, remaining, []Cents{0, 950, 400})
			monEq(t, TakeInOrder(remaining, []int{0}, 50), 0)
		})
	})

	t.Run("tax", func(t *testing.T) {
		t.Run("works out the tax that a price includes", func(t *testing.T) {
			monEq(t, monMust(IncludedTax(1200, 2000))(t), 200)
			monEq(t, monMust(IncludedTax(1000, 2000))(t), 167)
			monEq(t, monMust(IncludedTax(1000, 0))(t), 0)
		})

		t.Run("rejects a tax rate that is not whole basis points", func(t *testing.T) {
			_, err := IncludedTax(1000, -1)
			monErr(t, err, "tax rate must be a whole number of basis points")
		})
	})

	t.Run("formats", func(t *testing.T) {
		t.Run("formats cents as units and hundredths", func(t *testing.T) {
			monEq(t, []string{FormatCents(1234), FormatCents(5), FormatCents(0), FormatCents(-150)},
				[]string{"12.34", "0.05", "0.00", "-1.50"})
		})

		t.Run("formats money with a sign and groups of thousands", func(t *testing.T) {
			monEq(t, FormatMoney(123456, "£"), "£1,234.56")
			monEq(t, FormatMoney(100000000, "$"), "$1,000,000.00")
			monEq(t, FormatMoney(-99, "£"), "-£0.99")
		})

		t.Run("parses an amount back into cents", func(t *testing.T) {
			monEq(t, monMust(ParseCents("12.34"))(t), 1234)
			monEq(t, monMust(ParseCents(" 7 "))(t), 700)
			monEq(t, monMust(ParseCents("-0.50"))(t), -50)
			_, err := ParseCents("12.3")
			monErr(t, err, "12.3 is not an amount")
		})
	})
}
