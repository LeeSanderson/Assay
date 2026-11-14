package names

import "testing"

func TestNormaliseTrims(t *testing.T) {
	if got := Normalise("  apple "); got != "apple" {
		t.Fatalf("Normalise = %q, want %q", got, "apple")
	}
}

func TestNormaliseLowersCase(t *testing.T) {
	if got := Normalise("Apple"); got != "apple" {
		t.Fatalf("Normalise = %q, want %q", got, "apple")
	}
}
