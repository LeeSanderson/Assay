package tally

import (
	"slices"
	"testing"
)

func TestTop(t *testing.T) {
	cases := []struct {
		name   string
		counts map[string]int
		k      int
		want   []string
	}{
		{"the highest counts first", map[string]int{"apple": 2, "pear": 5, "plum": 1}, 2,
			[]string{"pear", "apple"}},
		{"a tie by name", map[string]int{"pear": 3, "apple": 3}, 2, []string{"apple", "pear"}},
		{"every name when k is larger", map[string]int{"apple": 1}, 5, []string{"apple"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			tally := New()
			for name, n := range c.counts {
				tally.Add(name, n)
			}
			got, err := tally.Top(c.k)
			if err != nil {
				t.Fatalf("Top(%d) error: %v", c.k, err)
			}
			if !slices.Equal(got, c.want) {
				t.Fatalf("Top(%d) = %v, want %v", c.k, got, c.want)
			}
		})
	}
}
