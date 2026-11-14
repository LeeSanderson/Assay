package domain

import (
	"fmt"
	"slices"
	"strings"
	"testing"
)

func idsEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := idsShow(got), idsShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func idsShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func idsSorted(ids []string, order func(a, b string) int) []string {
	slices.SortFunc(ids, order)
	return ids
}

func TestIDs(t *testing.T) {
	t.Run("identifiers", func(t *testing.T) {
		t.Run("reads the number at the end of an id", func(t *testing.T) {
			idsEq(t, IDNumber("order-12"), 12)
			idsEq(t, IDNumber("apple"), 0)
		})

		t.Run("orders ids of one kind by their number", func(t *testing.T) {
			idsEq(t, idsSorted([]string{"order-10", "order-9", "order-1"}, CompareIDs),
				[]string{"order-1", "order-9", "order-10"})
			idsEq(t, idsSorted([]string{"payment-1", "order-2"}, CompareIDs), []string{"order-2", "payment-1"})
		})

		t.Run("orders texts by their code units", func(t *testing.T) {
			idsEq(t, idsSorted([]string{"pear", "Apple", "apple"}, CompareText), []string{"Apple", "apple", "pear"})
		})

		t.Run("names a prefix for each kind of record", func(t *testing.T) {
			idsEq(t, []string{Prefix.Order, Prefix.Payment, Prefix.Shipment}, []string{"order", "payment", "shipment"})
		})
	})
}
