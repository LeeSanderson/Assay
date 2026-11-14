// Orders: what the checkout placed, and what happens to an order after it.
// A placed order is paid; it can then ship or be cancelled, once. The units of
// a shipped order can be returned; when all of them are, the order is returned.

package shop

import (
	"cmp"
	"fmt"
	"slices"
)

type OrderStatus string // "paid", "shipped", "cancelled" or "returned"

type OrderLine struct {
	SKU       string
	Name      string
	UnitPrice int
	Quantity  int
	Discounts []Discount // the part of each discount on this line
}

type Order struct {
	ID          string
	Lines       []OrderLine
	Subtotal    int
	Discounts   []Discount
	Total       int
	Status      OrderStatus
	PaymentID   string
	PlacedOn    string
	CreditNotes []CreditNote // the credit notes of its returns
}

type SKUSales struct {
	SKU      string
	Quantity int
}

type OrderRepository interface {
	Get(id string) (Order, bool)
	Save(order Order)
	List() []Order
}

type InMemoryOrderRepository struct {
	orders map[string]Order
	order  []string
}

func NewInMemoryOrderRepository() *InMemoryOrderRepository {
	return &InMemoryOrderRepository{orders: map[string]Order{}}
}

func (r *InMemoryOrderRepository) Get(id string) (Order, bool) {
	order, ok := r.orders[id]
	return copyOrder(order), ok
}

func (r *InMemoryOrderRepository) Save(order Order) {
	if _, ok := r.orders[order.ID]; !ok {
		r.order = append(r.order, order.ID)
	}
	r.orders[order.ID] = copyOrder(order)
}

// List gives the orders in the order that they were first saved.
func (r *InMemoryOrderRepository) List() []Order {
	list := make([]Order, 0, len(r.order))
	for _, id := range r.order {
		list = append(list, copyOrder(r.orders[id]))
	}
	return list
}

type Orders struct {
	repository OrderRepository
	inventory  *Inventory
	payments   PaymentGateway
}

func NewOrders(repository OrderRepository, inventory *Inventory, payments PaymentGateway) *Orders {
	return &Orders{repository: repository, inventory: inventory, payments: payments}
}

func (o *Orders) Order(id string) (Order, error) {
	order, ok := o.repository.Get(id)
	if !ok {
		return Order{}, fmt.Errorf("unknown order %s", id)
	}
	return order, nil
}

func (o *Orders) WithStatus(status OrderStatus) []Order {
	return slices.DeleteFunc(o.repository.List(), func(order Order) bool { return order.Status != status })
}

// Ship ships a paid order: its reserved stock leaves the inventory.
func (o *Orders) Ship(id string) error {
	order, err := o.paidOrder(id)
	if err != nil {
		return err
	}
	if err := o.inventory.Commit(id); err != nil {
		return err
	}
	order.Status = "shipped"
	o.repository.Save(order)
	return nil
}

// Cancel cancels a paid order: it releases the stock and refunds any payment.
func (o *Orders) Cancel(id string) error {
	order, err := o.paidOrder(id)
	if err != nil {
		return err
	}
	if order.PaymentID != "" {
		if _, err := o.payments.Refund(order.PaymentID); err != nil {
			return err
		}
	}
	if err := o.inventory.Release(id); err != nil {
		return err
	}
	order.Status = "cancelled"
	o.repository.Save(order)
	return nil
}

// Revenue gives the sum of the totals of the orders that are not cancelled,
// less what their credit notes refunded.
func (o *Orders) Revenue() (revenue int) {
	for _, order := range o.repository.List() {
		if order.Status != "cancelled" {
			revenue += order.Total
			for _, note := range order.CreditNotes {
				revenue -= note.Amount
			}
		}
	}
	return revenue
}

// BestSellers gives the units sold and not returned of each SKU over the
// orders that are not cancelled, most first, and in SKU order on a tie; at
// most limit of them.
func (o *Orders) BestSellers(limit int) []SKUSales {
	units := map[string]int{}
	for _, order := range o.repository.List() {
		if order.Status == "cancelled" {
			continue
		}
		for _, line := range order.Lines {
			units[line.SKU] += line.Quantity - returnedUnits(order, line.SKU)
		}
	}
	sales := make([]SKUSales, 0, len(units))
	for sku, quantity := range units {
		if quantity > 0 {
			sales = append(sales, SKUSales{SKU: sku, Quantity: quantity})
		}
	}
	slices.SortFunc(sales, func(a, b SKUSales) int {
		return cmp.Or(cmp.Compare(b.Quantity, a.Quantity), cmp.Compare(a.SKU, b.SKU))
	})
	return sales[:min(limit, len(sales))]
}

func (o *Orders) paidOrder(id string) (Order, error) {
	order, err := o.Order(id)
	if err != nil {
		return Order{}, err
	}
	if order.Status != "paid" {
		return Order{}, fmt.Errorf("order %s is %s", id, order.Status)
	}
	return order, nil
}

// returnedUnits gives the units of the SKU that the credit notes of the order
// have returned.
func returnedUnits(order Order, sku string) int {
	units := 0
	for _, note := range order.CreditNotes {
		for _, line := range note.Lines {
			if line.SKU == sku {
				units += line.Quantity
			}
		}
	}
	return units
}

func copyOrder(order Order) Order {
	order.Lines = append(order.Lines[:0:0], order.Lines...)
	for i := range order.Lines {
		order.Lines[i].Discounts = append(order.Lines[i].Discounts[:0:0], order.Lines[i].Discounts...)
	}
	order.Discounts = append(order.Discounts[:0:0], order.Discounts...)
	order.CreditNotes = append(order.CreditNotes[:0:0], order.CreditNotes...)
	for i, note := range order.CreditNotes {
		order.CreditNotes[i].Lines = append(note.Lines[:0:0], note.Lines...)
		order.CreditNotes[i].Discounts = append(note.Discounts[:0:0], note.Discounts...)
	}
	return order
}
