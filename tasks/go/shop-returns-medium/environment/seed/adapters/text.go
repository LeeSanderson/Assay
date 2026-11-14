// The documents of the shop as plain text: the receipt of an order, an
// invoice, a shipping label, a packing slip, the statement of an account,
// and the event log as JSON lines. Each row puts its label on the left and its
// amount on the right of a fixed width; amounts show as units and hundredths.

package adapters

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"

	. "shop/domain"
)

const width = 40

// Receipt gives one line per order line, then the subtotal, one line per
// discount, and the total. A discount shows as a negative amount.
func Receipt(order Order) string {
	rows := []string{fmt.Sprintf("Order %s (%s)", order.ID, order.PlacedOn)}
	for _, line := range order.Lines {
		rows = append(rows, row(fmt.Sprintf("%d x %s", line.Quantity, line.Name), LineTotal(line)))
	}
	rows = append(rows, row("Subtotal", order.Subtotal))
	rows = append(rows, discountRows(order.Discounts)...)
	rows = append(rows, row("Total", order.Total))
	if order.Status != "paid" {
		rows = append(rows, "Status: "+string(order.Status))
	}
	return strings.Join(rows, "\n") + "\n"
}

// InvoiceText gives the heading, one line per invoice line, the subtotal,
// the discounts, the total, and the tax that the total includes, with its
// rate.
func InvoiceText(invoice Invoice) string {
	rows := []string{fmt.Sprintf("Invoice %s (%s)", invoice.Number, invoice.IssuedOn), "Order " + invoice.OrderID}
	if invoice.CustomerID != "" {
		rows[1] += " for " + invoice.CustomerID
	}
	for _, line := range invoice.Lines {
		label := fmt.Sprintf("%d x %s @ %s", line.Quantity, line.Description, FormatCents(line.UnitPrice))
		rows = append(rows, row(label, line.Amount))
	}
	rows = append(rows, row("Subtotal", invoice.Subtotal))
	rows = append(rows, discountRows(invoice.Discounts)...)
	rows = append(rows, row("Total", invoice.Total), row("Tax included at "+FormatRate(invoice.TaxRate), invoice.Tax))
	return strings.Join(rows, "\n") + "\n"
}

// ShippingLabel gives the label of a shipment: its id, its order, the
// address and the units.
func ShippingLabel(shipment Shipment) string {
	plural := "s"
	if shipment.Parcels == 1 {
		plural = ""
	}
	return fmt.Sprintf("Shipment %s for order %s\nTo: %s\nUnits: %d in %d parcel%s\nZone: %s\n", shipment.ID,
		shipment.OrderID, FormatAddress(shipment.Address), shipment.Units, shipment.Parcels, plural, shipment.Zone)
}

// PackingSlip gives the packing slip of an order: what goes in the box, with
// no prices.
func PackingSlip(order Order, shipment Shipment) string {
	rows := []string{"Packing slip for order " + order.ID, "Ship to: " + FormatAddress(shipment.Address)}
	for _, line := range order.Lines {
		rows = append(rows, fmt.Sprintf("[ ] %3d x %s %s", line.Quantity, line.SKU, line.Name))
	}
	rows = append(rows, fmt.Sprintf("Units: %d", shipment.Units))
	return strings.Join(rows, "\n") + "\n"
}

// StatementText gives the statement of an account: one row for each entry,
// with its date, and the balances. Store credit shows as an amount; points
// as a count.
func StatementText(statement Statement) string {
	rows := []string{"Statement of " + statement.CustomerID}
	for _, entry := range statement.Entries {
		amount := fmt.Sprintf("%d points", entry.Amount)
		if entry.Kind == "credit" {
			amount = FormatCents(entry.Amount)
		}
		rows = append(rows, align(entry.On+" "+entry.Reason, amount))
	}
	rows = append(rows, row("Store credit", statement.Credit), fmt.Sprintf("Points: %d", statement.Points))
	return strings.Join(rows, "\n") + "\n"
}

// EventsAsJSONLines gives the events, one JSON object a line, for another
// system to read.
func EventsAsJSONLines(events []ShopEvent) string {
	text := ""
	for _, event := range events {
		line, _ := json.Marshal(event)
		text += string(line) + "\n"
	}
	return text
}

// EventsFromJSONLines reads events back from JSON lines; a blank line is
// skipped. Numbers in the data come back as ints.
func EventsFromJSONLines(text string) ([]ShopEvent, error) {
	events := []ShopEvent{}
	for i, line := range strings.Split(text, "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var event ShopEvent
		decoder := json.NewDecoder(bytes.NewReader([]byte(line)))
		decoder.UseNumber()
		if err := decoder.Decode(&event); err != nil || event.ID == "" || event.Type == "" {
			return nil, Invalid(fmt.Sprintf("line %d is not an event", i+1))
		}
		for key, value := range event.Data {
			if number, ok := value.(json.Number); ok {
				n, _ := number.Int64()
				event.Data[key] = int(n)
			}
		}
		events = append(events, event)
	}
	return events, nil
}

// FormatRate shows a rate in basis points as a percentage: 2000 is `20%`,
// 550 is `5.5%`.
func FormatRate(rate int) string {
	if rate%100 == 0 {
		return fmt.Sprintf("%d%%", rate/100)
	}
	return fmt.Sprintf("%d.%s%%", rate/100, strings.TrimSuffix(fmt.Sprintf("%02d", rate%100), "0"))
}

func discountRows(discounts []Discount) []string {
	var rows []string
	for _, discount := range discounts {
		rows = append(rows, row("Discount "+discount.PromotionID, -discount.Amount))
	}
	return rows
}

func row(label string, cents Cents) string { return align(label, FormatCents(cents)) }

func align(label, amount string) string {
	return label + strings.Repeat(" ", max(1, width-len(label)-len(amount))) + amount
}
