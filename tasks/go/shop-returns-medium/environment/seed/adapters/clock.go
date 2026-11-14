// The clock and the identifiers of the shop in memory, so that the tests and
// the shop's users can fix them.

package adapters

import (
	"fmt"

	. "shop/domain"
)

// FixedClock is a Clock that stays on one date until it is set to another.
// Dates are strings in the form YYYY-MM-DD.
type FixedClock struct {
	date IsoDate
}

func NewFixedClock(date IsoDate) *FixedClock { return &FixedClock{date: date} }

func (c *FixedClock) Today() IsoDate { return c.date }

func (c *FixedClock) Set(date IsoDate) { c.date = date }

// Advance moves the clock on by whole days.
func (c *FixedClock) Advance(days int) error {
	date, err := AddDays(c.date, days)
	if err == nil {
		c.date = date
	}
	return err
}

// SequentialIDs is an IDSource that gives `<prefix>-1`, `<prefix>-2` and so
// on, with one count for each prefix.
type SequentialIDs struct {
	counts map[string]int
}

func NewSequentialIDs() *SequentialIDs { return &SequentialIDs{counts: map[string]int{}} }

func (s *SequentialIDs) Next(prefix string) string {
	s.counts[prefix]++
	return fmt.Sprintf("%s-%d", prefix, s.counts[prefix])
}

// Given gives how many ids of the prefix it has given.
func (s *SequentialIDs) Given(prefix string) int { return s.counts[prefix] }
