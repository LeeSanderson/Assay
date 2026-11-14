// Events: the log of what happened in the shop, oldest first. The services do
// not write events. The event log learns of each change from the stores: a
// recording store (adapters/recording.go) compares each record that it saves
// with the record that it held, and these rules turn the change into an
// event, or into none.

package domain

import (
	"maps"
	"strings"
)

// EventData is the data of an event: a few plain values (strings and ints),
// never a whole record.
type EventData map[string]any

type ShopEvent struct {
	ID      string    `json:"id"`
	Type    string    `json:"type"`    // `<record>-<what happened>`, as `order-placed`
	Subject string    `json:"subject"` // the id of the record
	On      IsoDate   `json:"on"`
	Data    EventData `json:"data"`
}

type EventStore interface {
	Append(event ShopEvent)
	List() []ShopEvent // oldest first
}

// Change is what a rule gives for a change: the type, the subject and the
// data.
type Change struct {
	Type    string
	Subject string
	Data    EventData
}

// ChangeSink is where a recording store sends the changes that it sees: the
// event log.
type ChangeSink interface {
	Record(change Change) (ShopEvent, error)
}

// OrderChange: a new order is placed; a change of status gives
// `order-<status>`. `before` is nil for a new record.
func OrderChange(before *Order, after Order) (Change, bool) {
	data := EventData{"total": after.Total}
	if after.CustomerID != "" {
		data["customerId"] = after.CustomerID
	}
	if before == nil {
		data["lines"] = len(after.Lines)
		return Change{"order-placed", after.ID, data}, true
	}
	return Change{"order-" + string(after.Status), after.ID, data}, before.Status != after.Status
}

// ShipmentChange: a new shipment is created; a change of status gives
// `shipment-<status>`.
func ShipmentChange(before *Shipment, after Shipment) (Change, bool) {
	data := EventData{"orderId": after.OrderID}
	if before == nil {
		data["cost"] = after.Cost
		return Change{"shipment-created", after.ID, data}, true
	}
	if after.TrackingCode != "" {
		data["trackingCode"] = after.TrackingCode
	}
	return Change{"shipment-" + string(after.Status), after.ID, data}, before.Status != after.Status
}

// InvoiceChange: an invoice is issued once, and never changes.
func InvoiceChange(before *Invoice, after Invoice) (Change, bool) {
	data := EventData{"orderId": after.OrderID, "number": after.Number, "total": after.Total}
	return Change{"invoice-issued", after.ID, data}, before == nil
}

// CustomerChange: a new customer registers; a change of name, email or
// address updates it; and a customer can close its account.
func CustomerChange(before *Customer, after Customer) (Change, bool) {
	email := EventData{"email": after.Email}
	if before == nil {
		return Change{"customer-registered", after.ID, email}, true
	}
	if before.ClosedOn == "" && after.ClosedOn != "" {
		return Change{"customer-closed", after.ID, email}, true
	}
	var changed []string
	if before.Name != after.Name {
		changed = append(changed, "name")
	}
	if before.Email != after.Email {
		changed = append(changed, "email")
	}
	a, b := before.Address, after.Address
	if (a == nil) != (b == nil) || (a != nil && *a != *b) {
		changed = append(changed, "address")
	}
	fields := EventData{"fields": strings.Join(changed, ",")}
	return Change{"customer-updated", after.ID, fields}, len(changed) > 0
}

func CopyEvent(event ShopEvent) ShopEvent {
	event.Data = maps.Clone(event.Data)
	return event
}
