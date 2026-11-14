// Comma-separated values, for the reports: one header row of column names,
// then one row for each record. A value with a comma, a quote or a line
// break goes in quotes, with each quote doubled. Rows end with `\n`.

package adapters

import (
	"fmt"
	"slices"
	"strings"

	. "shop/domain"
)

type CSVValue = any // a string or an int

// Column is a column of a table: its heading and how to read its value from
// a row.
type Column[T any] struct {
	Heading string
	Value   func(row T) CSVValue
}

func ToCSV[T any](rows []T, columns []Column[T]) string {
	var lines []string
	for i := -1; i < len(rows); i++ {
		var values []string
		for _, column := range columns {
			value := column.Heading
			if i >= 0 {
				value = fmt.Sprint(column.Value(rows[i]))
			}
			values = append(values, quote(value))
		}
		lines = append(lines, strings.Join(values, ","))
	}
	return strings.Join(lines, "\n") + "\n"
}

// ParseCSV reads CSV text back into rows of strings, the header row first.
func ParseCSV(text string) [][]string {
	var rows [][]string
	var row []string
	field, quoted := "", false
	for i := 0; i < len(text); i++ {
		char := text[i]
		switch {
		case quoted && char == '"' && i+1 < len(text) && text[i+1] == '"':
			field += `"`
			i++
		case char == '"':
			quoted = !quoted
		case quoted || (char != ',' && char != '\n'):
			field += text[i : i+1]
		case char == ',':
			row, field = append(row, field), ""
		default: // the end of a row
			rows, row, field = append(rows, append(row, field)), nil, ""
		}
	}
	if field != "" || len(row) > 0 {
		rows = append(rows, append(row, field))
	}
	return rows
}

// ProductRows gives the rows of a price list in CSV, whose header row names
// the columns `sku`, `name` and `price`, in any order. A row with too few
// values gets empty ones.
func ProductRows(text string) ([]ProductRow, error) {
	rows := append(ParseCSV(text), nil)
	var columns []string
	for _, heading := range rows[0] {
		columns = append(columns, strings.ToLower(strings.TrimSpace(heading)))
	}
	for _, wanted := range []string{"sku", "name", "price"} {
		if !slices.Contains(columns, wanted) {
			return nil, Invalid("the price list has no " + wanted + " column")
		}
	}
	at := func(row []string, heading string) string {
		if i := slices.Index(columns, heading); i < len(row) {
			return row[i]
		}
		return ""
	}
	products := []ProductRow{}
	for _, row := range rows[1 : len(rows)-1] {
		if strings.TrimSpace(strings.Join(row, "")) != "" {
			products = append(products, ProductRow{SKU: at(row, "sku"), Name: at(row, "name"), Price: at(row, "price")})
		}
	}
	return products, nil
}

// The reports as CSV, amounts as units and hundredths.

func DailySalesCSV(rows []DailySales) string {
	return ToCSV(rows, []Column[DailySales]{
		{"date", func(r DailySales) CSVValue { return r.Date }},
		{"orders", func(r DailySales) CSVValue { return r.Orders }},
		{"revenue", func(r DailySales) CSVValue { return FormatCents(r.Revenue) }},
	})
}

func PromotionUsageCSV(rows []PromotionUsage) string {
	return ToCSV(rows, []Column[PromotionUsage]{
		{"promotion", func(r PromotionUsage) CSVValue { return r.PromotionID }},
		{"orders", func(r PromotionUsage) CSVValue { return r.Orders }},
		{"amount", func(r PromotionUsage) CSVValue { return FormatCents(r.Amount) }},
	})
}

func StockValuesCSV(rows []StockValue) string {
	return ToCSV(rows, []Column[StockValue]{
		{"sku", func(r StockValue) CSVValue { return r.SKU }},
		{"on hand", func(r StockValue) CSVValue { return r.OnHand }},
		{"unit price", func(r StockValue) CSVValue { return FormatCents(r.UnitPrice) }},
		{"value", func(r StockValue) CSVValue { return FormatCents(r.Value) }},
	})
}

func quote(value string) string {
	if strings.ContainsAny(value, "\",\n") {
		return `"` + strings.ReplaceAll(value, `"`, `""`) + `"`
	}
	return value
}
