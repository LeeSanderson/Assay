// Orders: what happens to an order after the checkout placed it. A paid
// order can ship or be cancelled, once. The revenue and the best sellers
// count only what the customers kept.

package services

import (
	"cmp"
	"maps"
	"slices"

	. "shop/domain"
)

type Orders struct {
	repository OrderRepository
	inventory  *Inventory
	payments   PaymentGateway
}

func NewOrders(repository OrderRepository, inventory *Inventory, payments PaymentGateway) *Orders {
	return &Orders{repository: repository, inventory: inventory, payments: payments}
}

func (o *Orders) Order(id string) (Order, error) {
	if order, ok := o.repository.Get(id); ok {
		return order, nil
	}
	return Order{}, NotFound("order", id)
}

// All gives every order, in the order that they were placed.
func (o *Orders) All() []Order { return o.repository.List() }

func (o *Orders) WithStatus(status OrderStatus) []Order {
	return o.Search(OrderFilter{Status: status})
}

// ForCustomer gives the orders of a customer, in the order that they were
// placed.
func (o *Orders) ForCustomer(customerID string) []Order {
	return slices.DeleteFunc(o.All(), func(order Order) bool { return order.CustomerID != customerID })
}

// PlacedBetween gives the orders placed in the period, both dates included.
func (o *Orders) PlacedBetween(from, to IsoDate) ([]Order, error) {
	if err := CheckPeriod(from, to); err != nil {
		return nil, err
	}
	return o.Search(OrderFilter{From: from, To: to}), nil
}

// Search gives the orders that match the filter, in the order that they
// were placed.
func (o *Orders) Search(filter OrderFilter) []Order {
	return slices.DeleteFunc(o.All(), func(order Order) bool { return !Matches(order, filter) })
}

// WaitingSince gives the paid orders placed more than `days` days before the
// date, which have waited too long to ship.
func (o *Orders) WaitingSince(date IsoDate, days int) []Order {
	return slices.DeleteFunc(o.WithStatus("paid"), func(order Order) bool {
		return DaysBetween(order.PlacedOn, date) <= days
	})
}

// Ship ships a paid order: its reserved stock leaves the inventory.
func (o *Orders) Ship(id string) error {
	shipped, err := o.move(id, "shipped")
	if err == nil {
		err = o.inventory.Commit(id)
	}
	if err == nil {
		o.repository.Save(shipped)
	}
	return err
}

// Cancel cancels a paid order: its stock is released and its payment, if it
// has one, refunded.
func (o *Orders) Cancel(id string) error {
	cancelled, err := o.move(id, "cancelled")
	if err == nil && cancelled.PaymentID != "" {
		_, err = o.payments.Refund(cancelled.PaymentID)
	}
	if err == nil {
		err = o.inventory.Release(id)
	}
	if err == nil {
		o.repository.Save(cancelled)
	}
	return err
}

func (o *Orders) move(id string, status OrderStatus) (Order, error) {
	order, err := o.Order(id)
	if err != nil {
		return Order{}, err
	}
	return MoveTo(order, status)
}

// CheckPaid checks that an order is paid, and so can still change.
func (o *Orders) CheckPaid(id string) (Order, error) {
	order, err := o.Order(id)
	if err = first(err, CheckStatus(order, "paid")); err != nil {
		return Order{}, err
	}
	return order, nil
}

// Revenue gives the sum of the totals of the orders that are not cancelled,
// less what their credit notes refunded.
func (o *Orders) Revenue() Cents {
	revenue := 0
	for _, order := range o.counted() {
		revenue += order.Total - Refunded(order)
	}
	return revenue
}

// AverageOrderValue gives the revenue per order that is not cancelled,
// rounded down; 0 with none.
func (o *Orders) AverageOrderValue() Cents {
	if counted := len(o.counted()); counted > 0 {
		return o.Revenue() / counted
	}
	return 0
}

// BestSellers gives the units sold and not returned of each SKU over the
// orders that are not cancelled, most first, and in SKU order on a tie; at
// most `limit` of them. A SKU with no such units is left out.
func (o *Orders) BestSellers(limit int) []SKUSales {
	units := map[string]int{}
	for _, order := range o.counted() {
		for _, line := range order.Lines {
			units[line.SKU] += line.Quantity - ReturnedUnits(order, line.SKU)
		}
	}
	sales := []SKUSales{}
	for _, sku := range slices.Sorted(maps.Keys(units)) {
		if units[sku] > 0 {
			sales = append(sales, SKUSales{SKU: sku, Quantity: units[sku]})
		}
	}
	slices.SortStableFunc(sales, func(a, b SKUSales) int { return cmp.Compare(b.Quantity, a.Quantity) })
	return sales[:min(limit, len(sales))]
}

func (o *Orders) counted() []Order {
	return slices.DeleteFunc(o.All(), func(order Order) bool { return !Counts(order) })
}
