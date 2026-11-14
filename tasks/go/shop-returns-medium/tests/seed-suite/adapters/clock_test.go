package adapters

import (
	"fmt"
	"strings"
	"testing"
)

func clockEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := clockShow(got), clockShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func clockShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func TestClock(t *testing.T) {
	t.Run("a fixed clock gives its date until it is set", func(t *testing.T) {
		clock := NewFixedClock("2026-03-10")
		clockEq(t, clock.Today(), "2026-03-10")
		clock.Set("2026-03-11")
		clockEq(t, clock.Today(), "2026-03-11")
	})

	t.Run("a fixed clock moves on by whole days", func(t *testing.T) {
		clock := NewFixedClock("2026-03-30")
		if err := clock.Advance(3); err != nil {
			t.Fatal(err)
		}
		clockEq(t, clock.Today(), "2026-04-02")
	})

	t.Run("sequential ids count from 1 for each prefix", func(t *testing.T) {
		ids := NewSequentialIDs()
		clockEq(t, []string{ids.Next("order"), ids.Next("order"), ids.Next("payment")},
			[]string{"order-1", "order-2", "payment-1"})
		clockEq(t, []int{ids.Given("order"), ids.Given("invoice")}, []int{2, 0})
	})
}
