// The receipt of an order, as plain text. Amounts are whole cents, shown as
// units and hundredths: 1234 cents is `12.34`.

package shop

import (
	"fmt"
	"strings"
)

const receiptWidth = 40

func FormatCents(cents int) string {
	sign := ""
	if cents < 0 {
		sign = "-"
		cents = -cents
	}
	return fmt.Sprintf("%s%d.%02d", sign, cents/100, cents%100)
}

// Receipt gives one line per order line, then the subtotal, one line per
// discount, and the total. A discount shows as a negative amount.
func Receipt(order Order) string {
	rows := []string{fmt.Sprintf("Order %s (%s)", order.ID, order.PlacedOn)}
	for _, line := range order.Lines {
		rows = append(rows, receiptRow(fmt.Sprintf("%d x %s", line.Quantity, line.Name), line.UnitPrice*line.Quantity))
	}
	rows = append(rows, receiptRow("Subtotal", order.Subtotal))
	for _, discount := range order.Discounts {
		rows = append(rows, receiptRow("Discount "+discount.PromotionID, -discount.Amount))
	}
	rows = append(rows, receiptRow("Total", order.Total))
	if order.Status != "paid" {
		rows = append(rows, fmt.Sprintf("Status: %s", order.Status))
	}
	return strings.Join(rows, "\n") + "\n"
}

func receiptRow(label string, cents int) string {
	amount := FormatCents(cents)
	gap := receiptWidth - len(label) - len(amount)
	if gap < 1 {
		gap = 1
	}
	return label + strings.Repeat(" ", gap) + amount
}
