package adapters

import (
	"fmt"
	"strings"
	"testing"

	. "shop/domain"
)

func csvEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := csvShow(got), csvShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func csvShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

type csvUnits struct {
	sku   string
	units int
}

func TestCSV(t *testing.T) {
	t.Run("csv", func(t *testing.T) {
		t.Run("writes a header row and one row for each record", func(t *testing.T) {
			rows := []csvUnits{{"apple", 2}, {"pear", 1}}
			csvEq(t, ToCSV(rows, []Column[csvUnits]{
				{Heading: "sku", Value: func(r csvUnits) CSVValue { return r.sku }},
				{Heading: "units", Value: func(r csvUnits) CSVValue { return r.units }},
			}), "sku,units\napple,2\npear,1\n")
		})

		t.Run("quotes a value with a comma, a quote or a line break", func(t *testing.T) {
			rows := []string{`Apples, "red"`}
			csvEq(t, ToCSV(rows, []Column[string]{
				{Heading: "name", Value: func(r string) CSVValue { return r }},
			}), "name\n\"Apples, \"\"red\"\"\"\n")
		})

		t.Run("reads quoted values back", func(t *testing.T) {
			csvEq(t, ParseCSV("name,price\n\"Apples, \"\"red\"\"\",2.50\nPear,10.00\n"), [][]string{
				{"name", "price"}, {`Apples, "red"`, "2.50"}, {"Pear", "10.00"},
			})
		})

		t.Run("writes reports with amounts in units and hundredths", func(t *testing.T) {
			csvEq(t, DailySalesCSV([]DailySales{{Date: "2026-03-10", Orders: 2, Revenue: 1350}}),
				"date,orders,revenue\n2026-03-10,2,13.50\n")
			csvEq(t, StockValuesCSV([]StockValue{{SKU: "apple", OnHand: 4, UnitPrice: 250, Value: 1000}}),
				"sku,on hand,unit price,value\napple,4,2.50,10.00\n")
		})
	})

	t.Run("price lists", func(t *testing.T) {
		t.Run("reads the rows of a price list by the names of its columns", func(t *testing.T) {
			rows, err := ProductRows("price,sku,name\n2.50,apple,Apple\n\n10.00,pear,Pear\n")
			if err != nil {
				t.Fatal(err)
			}
			csvEq(t, rows, []ProductRow{
				{SKU: "apple", Name: "Apple", Price: "2.50"},
				{SKU: "pear", Name: "Pear", Price: "10.00"},
			})
		})

		t.Run("rejects a price list without a column that it needs", func(t *testing.T) {
			_, err := ProductRows("sku,name\napple,Apple\n")
			if err == nil || err.Error() != "the price list has no price column" {
				t.Fatalf("got error %v", err)
			}
		})
	})
}
