// Orders: what the checkout placed, and what happens to an order after it.
// A placed order is paid; it can then ship or be cancelled, once.

package shop

import (
	"fmt"
	"sort"
)

type OrderStatus string // "paid", "shipped" or "cancelled"

type OrderLine struct {
	SKU       string
	Name      string
	UnitPrice int
	Quantity  int
}

type Order struct {
	ID        string
	Lines     []OrderLine
	Subtotal  int
	Discounts []Discount
	Total     int
	Status    OrderStatus
	PaymentID string
	PlacedOn  string
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
	var orders []Order
	for _, order := range o.repository.List() {
		if order.Status == status {
			orders = append(orders, order)
		}
	}
	return orders
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

// Cancel cancels a paid order: its stock is released and its payment, if it
// has one, refunded.
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

// Revenue gives the sum of the totals of the orders that are not cancelled.
func (o *Orders) Revenue() int {
	revenue := 0
	for _, order := range o.repository.List() {
		if order.Status != "cancelled" {
			revenue += order.Total
		}
	}
	return revenue
}

// BestSellers gives the units sold of each SKU over the orders that are not
// cancelled, most first, and in SKU order on a tie; at most limit of them.
func (o *Orders) BestSellers(limit int) []SKUSales {
	units := map[string]int{}
	for _, order := range o.repository.List() {
		if order.Status == "cancelled" {
			continue
		}
		for _, line := range order.Lines {
			units[line.SKU] += line.Quantity
		}
	}
	sales := make([]SKUSales, 0, len(units))
	for sku, quantity := range units {
		sales = append(sales, SKUSales{SKU: sku, Quantity: quantity})
	}
	sort.Slice(sales, func(i, j int) bool {
		if sales[i].Quantity != sales[j].Quantity {
			return sales[i].Quantity > sales[j].Quantity
		}
		return sales[i].SKU < sales[j].SKU
	})
	if len(sales) > limit {
		sales = sales[:limit]
	}
	return sales
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

func copyOrder(order Order) Order {
	order.Lines = append(order.Lines[:0:0], order.Lines...)
	order.Discounts = append(order.Discounts[:0:0], order.Discounts...)
	return order
}
