// Money. Every amount in the shop is a whole number of cents, of one
// currency, held in a plain int: 1234 is 12.34. The shop never holds a
// fraction of a cent. Where a rule divides an amount (a percentage, a share,
// a tax), it rounds down; the helpers below are the only places that divide
// money.

package domain

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

type Cents = int

const Zero Cents = 0

// CheckCents checks that an amount is at least `least`.
func CheckCents(amount Cents, what string, least int) error {
	return Check(amount >= least, fmt.Sprintf("%s must be at least %d", what, least))
}

func Sum(amounts []Cents) Cents {
	total := 0
	for _, amount := range amounts {
		total += amount
	}
	return total
}

// Times gives the price of `quantity` units at `unitPrice` each.
func Times(unitPrice Cents, quantity int) Cents { return unitPrice * quantity }

// PercentOf gives `percent` per cent of the amount, rounded down.
func PercentOf(amount Cents, percent int) Cents { return floorDiv(amount*percent, 100) }

// ShareOf gives the share of `amount` that `part` is of `whole`, rounded
// down: the part of a discount that a share of the units carries.
func ShareOf(amount Cents, part, whole int) (Cents, error) {
	if whole <= 0 {
		return 0, Invalid("a share needs a whole above 0")
	}
	return floorDiv(amount*part, whole), nil
}

// Allocate splits an amount over weights in proportion, each part rounded
// down, and gives the cents that the rounding leaves over one each to the
// first parts. The parts always add up to the amount.
func Allocate(amount Cents, weights []int) []Cents {
	whole := Sum(weights)
	parts := make([]Cents, len(weights))
	if whole == 0 {
		return parts
	}
	for i, weight := range weights {
		parts[i] = floorDiv(amount*weight, whole)
	}
	left := amount - Sum(parts)
	for i := 0; left > 0 && i < len(parts); i++ {
		if weights[i] > 0 {
			parts[i]++
			left--
		}
	}
	return parts
}

// IncludedTax gives the tax that a price holds when the price includes tax
// at `rate` basis points (2000 is 20%): the price less the price without
// tax, which rounds down.
func IncludedTax(price Cents, rate int) (Cents, error) {
	if rate < 0 {
		return 0, Invalid("tax rate must be a whole number of basis points")
	}
	return price - floorDiv(price*10000, 10000+rate), nil
}

// TakeInOrder takes up to `amount` from the remaining amounts at the given
// indexes, in order, and gives what it took. It changes `remaining`.
func TakeInOrder(remaining []Cents, indexes []int, amount Cents) Cents {
	left := amount
	for _, i := range indexes {
		take := min(left, remaining[i])
		remaining[i] -= take
		left -= take
	}
	return amount - left
}

// FormatCents shows an amount as units and hundredths: 1234 is `12.34`,
// -150 is `-1.50`.
func FormatCents(cents Cents) string {
	sign := ""
	if cents < 0 {
		sign, cents = "-", -cents
	}
	return fmt.Sprintf("%s%d.%02d", sign, cents/100, cents%100)
}

// FormatMoney shows an amount for people to read, with the currency sign and
// a comma between each group of three digits: 123456 is `£1,234.56`.
func FormatMoney(cents Cents, sign string) string {
	whole, hundredths, _ := strings.Cut(FormatCents(max(cents, -cents)), ".")
	for i := len(whole) - 3; i > 0; i -= 3 {
		whole = whole[:i] + "," + whole[i:]
	}
	if cents < 0 {
		sign = "-" + sign
	}
	return sign + whole + "." + hundredths
}

// SplitEvenly splits an amount into `parts` amounts that differ by at most
// one cent, the larger ones first.
func SplitEvenly(amount Cents, parts int) ([]Cents, error) {
	if parts < 1 {
		return nil, Invalid("parts must be at least 1")
	}
	weights := make([]int, parts)
	for i := range weights {
		weights[i] = 1
	}
	return Allocate(amount, weights), nil
}

// Max gives the larger of two amounts, and Min the smaller.
func Max(a, b Cents) Cents { return max(a, b) }

func Min(a, b Cents) Cents { return min(a, b) }

var amountPattern = regexp.MustCompile(`^(-?)(\d+)(?:\.(\d{2}))?$`)

// ParseCents reads `12.34` (or `12`, or `-0.50`) as cents.
func ParseCents(text string) (Cents, error) {
	match := amountPattern.FindStringSubmatch(strings.TrimSpace(text))
	if match == nil {
		return 0, Invalid(text + " is not an amount")
	}
	whole, _ := strconv.Atoi(match[2])
	hundredths, _ := strconv.Atoi("0" + match[3])
	cents := whole*100 + hundredths
	if match[1] == "-" {
		return -cents, nil
	}
	return cents, nil
}

// floorDiv divides and rounds down, as Math.floor does, below zero too.
func floorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
