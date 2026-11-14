// Package tally counts names.
package tally

import (
	"errors"
	"sort"

	"tally/names"
)

// Tally holds a count for each name.
type Tally struct {
	counts map[string]int
}

// New gives an empty tally.
func New() *Tally {
	return &Tally{counts: map[string]int{}}
}

// Add adds n to the count of name.
func (t *Tally) Add(name string, n int) {
	t.counts[names.Normalise(name)] += n
}

// Count gives the count of name.
func (t *Tally) Count(name string) int {
	return t.counts[names.Normalise(name)]
}

// Names gives the names in order.
func (t *Tally) Names() []string {
	out := make([]string, 0, len(t.counts))
	for name := range t.counts {
		out = append(out, name)
	}
	sort.Strings(out)
	return out
}

// Top gives the k names with the highest counts.
func (t *Tally) Top(k int) ([]string, error) {
	return nil, errors.New("not implemented")
}
