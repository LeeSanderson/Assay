// Orders: what the checkout placed. A placed order is paid; it can then ship
// or be cancelled, once. The lines and the amounts of an order stay as they
// were placed.

package domain

import "slices"

type OrderStatus string // `paid`, `shipped` or `cancelled`

type OrderLine struct {
	SKU       string
	Name      string
	UnitPrice Cents
	Quantity  int
}

type Order struct {
	ID         string
	Lines      []OrderLine
	Subtotal   Cents
	Discounts  []Discount
	Total      Cents
	Status     OrderStatus
	PaymentID  string // empty when the order cost nothing, and so had no payment
	PlacedOn   IsoDate
	CustomerID string // empty when a guest placed the order
}

type SKUSales struct {
	SKU      string
	Quantity int
}

type OrderRepository interface {
	Get(id string) (Order, bool)
	Save(order Order)
	List() []Order // in the order that they were first saved
}

// orderMoves holds the statuses that an order can move to from each status.
// A status that is not here moves nowhere.
var orderMoves = map[OrderStatus][]OrderStatus{"paid": {"shipped", "cancelled"}}

// MoveTo gives the order with its new status, or the error `order <id> is
// <status>` when its status does not allow the move.
func MoveTo(order Order, status OrderStatus) (Order, error) {
	if !slices.Contains(orderMoves[order.Status], status) {
		return Order{}, WrongState("order", order.ID, string(order.Status))
	}
	order = CopyOrder(order)
	order.Status = status
	return order, nil
}

// CheckStatus checks that the order has the status: `order <id> is <status>`
// when not.
func CheckStatus(order Order, status OrderStatus) error {
	if order.Status != status {
		return WrongState("order", order.ID, string(order.Status))
	}
	return nil
}

// Counts tells whether an order counts in the sales: unless it was cancelled.
func Counts(order Order) bool { return order.Status != "cancelled" }

func LineTotal(line OrderLine) Cents { return Times(line.UnitPrice, line.Quantity) }

func UnitsOf(order Order) int {
	units := 0
	for _, line := range order.Lines {
		units += line.Quantity
	}
	return units
}

func DiscountTotal(order Order) Cents {
	total := 0
	for _, discount := range order.Discounts {
		total += discount.Amount
	}
	return total
}

// OrderFilter is what to look for in the orders. Each field that is not
// empty must match; an empty filter matches every order.
type OrderFilter struct {
	Status     OrderStatus
	CustomerID string
	SKU        string  // the order has a line of the SKU
	From       IsoDate // placed on or after
	To         IsoDate // placed on or before
	MinTotal   Cents
}

func Matches(order Order, filter OrderFilter) bool {
	hasSKU := slices.ContainsFunc(order.Lines, func(line OrderLine) bool { return line.SKU == filter.SKU })
	return (filter.Status == "" || order.Status == filter.Status) &&
		(filter.CustomerID == "" || order.CustomerID == filter.CustomerID) &&
		(filter.SKU == "" || hasSKU) &&
		(filter.From == "" || order.PlacedOn >= filter.From) &&
		(filter.To == "" || order.PlacedOn <= filter.To) &&
		order.Total >= filter.MinTotal
}

// QuantityOf gives the quantity of a SKU over the lines of the order.
func QuantityOf(order Order, sku string) int {
	quantity := 0
	for _, line := range order.Lines {
		if line.SKU == sku {
			quantity += line.Quantity
		}
	}
	return quantity
}

func CopyOrder(order Order) Order {
	order.Lines = slices.Clone(order.Lines)
	order.Discounts = slices.Clone(order.Discounts)
	return order
}
