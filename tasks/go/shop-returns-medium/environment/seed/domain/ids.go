// Identifiers. Every record that the shop creates gets its id from an
// IDSource, as `<prefix>-<n>`: `order-1`, `payment-3`. The prefix names the
// kind of record; each kind has its own count. A product is the one record
// whose id the shop does not make: its SKU, which the caller gives.

package domain

import (
	"regexp"
	"strconv"
	"strings"
)

type IDSource interface {
	Next(prefix string) string
}

// Prefix names the prefix of each kind of record that the shop numbers.
var Prefix = struct {
	Order    string
	Payment  string
	Customer string
	Shipment string
	Invoice  string
	Event    string
	Entry    string
	Supplier string
	Purchase string
}{"order", "payment", "customer", "shipment", "invoice", "event", "entry", "supplier", "purchase"}

var idSuffix = regexp.MustCompile(`-(\d+)$`)

// IDNumber gives the number at the end of an id, or 0 when the id has none:
// `order-12` is 12.
func IDNumber(id string) int {
	match := idSuffix.FindStringSubmatch(id)
	if match == nil {
		return 0
	}
	n, _ := strconv.Atoi(match[1])
	return n
}

// CompareIDs orders ids of one kind by their number, so that `order-10`
// comes after `order-9`; ids of different kinds by their prefix.
func CompareIDs(a, b string) int {
	prefixA, prefixB := idSuffix.ReplaceAllString(a, ""), idSuffix.ReplaceAllString(b, "")
	if prefixA != prefixB {
		return CompareText(prefixA, prefixB)
	}
	return IDNumber(a) - IDNumber(b)
}

// CompareText orders two texts as the shop sorts SKUs and codes: by their
// bytes, which is the order of their code units for the ASCII of SKUs.
func CompareText(a, b string) int { return strings.Compare(a, b) }
