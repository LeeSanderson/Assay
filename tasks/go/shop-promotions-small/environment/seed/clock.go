// The date and the identifiers that the shop uses, behind interfaces so that
// the tests can fix them.

package shop

import "fmt"

type Clock interface {
	Today() string
}

// FixedClock stays on one date until it is set to another. Dates are strings
// in the form YYYY-MM-DD.
type FixedClock struct {
	date string
}

func NewFixedClock(date string) *FixedClock {
	return &FixedClock{date: date}
}

func (c *FixedClock) Today() string {
	return c.date
}

func (c *FixedClock) Set(date string) {
	c.date = date
}

type IDSource interface {
	Next(prefix string) string
}

// SequentialIDs gives `<prefix>-1`, `<prefix>-2` and so on, with one count
// for each prefix.
type SequentialIDs struct {
	counts map[string]int
}

func NewSequentialIDs() *SequentialIDs {
	return &SequentialIDs{counts: map[string]int{}}
}

func (s *SequentialIDs) Next(prefix string) string {
	s.counts[prefix]++
	return fmt.Sprintf("%s-%d", prefix, s.counts[prefix])
}
