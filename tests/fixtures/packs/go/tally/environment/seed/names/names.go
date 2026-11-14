// Package names keys the names of a tally.
package names

import "strings"

// Normalise gives a name as the tally keys it: trimmed and in lower case.
func Normalise(name string) string {
	return strings.ToLower(strings.TrimSpace(name))
}
