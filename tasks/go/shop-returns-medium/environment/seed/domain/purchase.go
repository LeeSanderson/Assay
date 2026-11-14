// Purchasing: the shop buys stock from its suppliers with purchase orders. A
// purchase order is drafted, then sent to the supplier, and its lines are
// received into the inventory, in one delivery or in several. A purchase
// order is received when every unit of every line has come in. What the
// shop pays a supplier (the unit cost) is not what it charges customers.

package domain

import "slices"

type Supplier struct {
	ID           string
	Name         string
	Email        string
	LeadTimeDays int // the days from sending an order to its delivery
}

type SupplierRepository interface {
	Get(id string) (Supplier, bool)
	Save(supplier Supplier)
	List() []Supplier
}

type PurchaseStatus string // `draft`, `sent`, `received` or `cancelled`

type PurchaseLine struct {
	SKU      string
	Quantity int
	UnitCost Cents
	Received int
}

type PurchaseOrder struct {
	ID         string
	SupplierID string
	Lines      []PurchaseLine
	Status     PurchaseStatus
	CreatedOn  IsoDate
	SentOn     IsoDate
	ExpectedOn IsoDate // the sent date plus the lead time of the supplier
}

type PurchaseRepository interface {
	Get(id string) (PurchaseOrder, bool)
	Save(order PurchaseOrder)
	List() []PurchaseOrder // in the order that they were drafted
}

func CheckSupplier(name, email string, leadTimeDays int) error {
	return first(CheckNotEmpty(name, "name"), CheckNotEmpty(email, "email"),
		Check(leadTimeDays >= 0, "lead time must be a whole number of days"))
}

func CheckPurchaseLine(sku string, quantity int, unitCost Cents) error {
	return first(CheckNotEmpty(sku, "SKU"), CheckQuantity(quantity),
		CheckCents(unitCost, "unit cost", 1))
}

// CheckPurchaseStatus checks that the purchase order has the status:
// `purchase <id> is <status>` when not.
func CheckPurchaseStatus(order PurchaseOrder, status PurchaseStatus) error {
	if order.Status != status {
		return WrongState("purchase", order.ID, string(order.Status))
	}
	return nil
}

// Outstanding gives the units of a line that have not come in yet.
func Outstanding(line PurchaseLine) int { return line.Quantity - line.Received }

func IsReceived(order PurchaseOrder) bool {
	return !slices.ContainsFunc(order.Lines, func(line PurchaseLine) bool { return Outstanding(line) > 0 })
}

// CostOfPurchase gives what the purchase order costs the shop, for every
// unit ordered.
func CostOfPurchase(order PurchaseOrder) Cents {
	cost := 0
	for _, line := range order.Lines {
		cost += Times(line.UnitCost, line.Quantity)
	}
	return cost
}

func CopyPurchase(order PurchaseOrder) PurchaseOrder {
	order.Lines = slices.Clone(order.Lines)
	return order
}

func CopySupplier(supplier Supplier) Supplier { return supplier }
