package tally

import (
	"slices"
	"testing"
)

func TestCountIsZeroAtFirst(t *testing.T) {
	if got := New().Count("apple"); got != 0 {
		t.Fatalf("Count = %d, want 0", got)
	}
}

func TestAddAddsToACount(t *testing.T) {
	tally := New()
	tally.Add("apple", 1)
	tally.Add("apple", 2)
	if got := tally.Count("apple"); got != 3 {
		t.Fatalf("Count = %d, want 3", got)
	}
}

func TestNamesAreInOrder(t *testing.T) {
	tally := New()
	tally.Add("pear", 1)
	tally.Add("apple", 1)
	if got, want := tally.Names(), []string{"apple", "pear"}; !slices.Equal(got, want) {
		t.Fatalf("Names = %v, want %v", got, want)
	}
}
