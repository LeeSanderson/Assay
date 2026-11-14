package shop

import (
	"reflect"
	"testing"
)

// clockWant fails the test unless got and want are deeply equal.
func clockWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestClock(t *testing.T) {
	t.Run("a fixed clock gives its date until it is set", func(t *testing.T) {
		clock := NewFixedClock("2026-03-10")
		clockWant(t, clock.Today(), "2026-03-10")
		clock.Set("2026-03-11")
		clockWant(t, clock.Today(), "2026-03-11")
	})

	t.Run("sequential ids count from 1 for each prefix", func(t *testing.T) {
		ids := NewSequentialIDs()
		got := []string{ids.Next("order"), ids.Next("order"), ids.Next("payment")}
		clockWant(t, got, []string{"order-1", "order-2", "payment-1"})
	})
}
