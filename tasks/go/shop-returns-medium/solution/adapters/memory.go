// The adapters of the shop in memory: a store for each kind of record, the
// payment gateway, and the outbox of the messages to customers. Each store
// keeps copies: what it gives back is a copy of what it holds, and what it
// saves is a copy of what it is given, so that a caller never changes a
// record that the store holds.

package adapters

import (
	"fmt"
	"slices"

	. "shop/domain"
)

// table holds records by key, in the order that each key was first saved.
type table[T any] struct {
	key  func(row T) string
	copy func(row T) T
	keys []string
	rows map[string]T
}

func newTable[T any](key func(T) string, copy func(T) T) *table[T] {
	return &table[T]{key: key, copy: copy, rows: map[string]T{}}
}

func (t *table[T]) get(key string) (T, bool) {
	row, ok := t.rows[key]
	return t.copy(row), ok
}

func (t *table[T]) save(row T) {
	key := t.key(row)
	if _, ok := t.rows[key]; !ok {
		t.keys = append(t.keys, key)
	}
	t.rows[key] = t.copy(row)
}

func (t *table[T]) remove(key string) {
	delete(t.rows, key)
	t.keys = slices.DeleteFunc(t.keys, func(k string) bool { return k == key })
}

func (t *table[T]) list() []T {
	list := []T{}
	for _, key := range t.keys {
		list = append(list, t.copy(t.rows[key]))
	}
	return list
}

// --- The stores ---------------------------------------------------------------

type InMemoryProductRepository struct{ rows *table[Product] }

func NewInMemoryProductRepository() *InMemoryProductRepository {
	return &InMemoryProductRepository{newTable(func(p Product) string { return p.SKU }, CopyProduct)}
}

func (r *InMemoryProductRepository) Get(sku string) (Product, bool) { return r.rows.get(sku) }

func (r *InMemoryProductRepository) Save(product Product) { r.rows.save(product) }

func (r *InMemoryProductRepository) List() []Product { return r.rows.list() }

type InMemoryOrderRepository struct{ rows *table[Order] }

func NewInMemoryOrderRepository() *InMemoryOrderRepository {
	return &InMemoryOrderRepository{newTable(func(o Order) string { return o.ID }, CopyOrder)}
}

func (r *InMemoryOrderRepository) Get(id string) (Order, bool) { return r.rows.get(id) }

func (r *InMemoryOrderRepository) Save(order Order) { r.rows.save(order) }

func (r *InMemoryOrderRepository) List() []Order { return r.rows.list() }

type InMemoryCustomerRepository struct{ rows *table[Customer] }

func NewInMemoryCustomerRepository() *InMemoryCustomerRepository {
	return &InMemoryCustomerRepository{newTable(func(c Customer) string { return c.ID }, CopyCustomer)}
}

func (r *InMemoryCustomerRepository) Get(id string) (Customer, bool) { return r.rows.get(id) }

func (r *InMemoryCustomerRepository) Save(customer Customer) { r.rows.save(customer) }

func (r *InMemoryCustomerRepository) List() []Customer { return r.rows.list() }

type InMemoryShipmentRepository struct{ rows *table[Shipment] }

func NewInMemoryShipmentRepository() *InMemoryShipmentRepository {
	return &InMemoryShipmentRepository{newTable(func(s Shipment) string { return s.ID }, CopyShipment)}
}

func (r *InMemoryShipmentRepository) Get(id string) (Shipment, bool) { return r.rows.get(id) }

func (r *InMemoryShipmentRepository) Save(shipment Shipment) { r.rows.save(shipment) }

func (r *InMemoryShipmentRepository) List() []Shipment { return r.rows.list() }

type InMemoryInvoiceRepository struct{ rows *table[Invoice] }

func NewInMemoryInvoiceRepository() *InMemoryInvoiceRepository {
	return &InMemoryInvoiceRepository{newTable(func(i Invoice) string { return i.ID }, CopyInvoice)}
}

func (r *InMemoryInvoiceRepository) Get(id string) (Invoice, bool) { return r.rows.get(id) }

func (r *InMemoryInvoiceRepository) Save(invoice Invoice) { r.rows.save(invoice) }

func (r *InMemoryInvoiceRepository) List() []Invoice { return r.rows.list() }

type InMemorySupplierRepository struct{ rows *table[Supplier] }

func NewInMemorySupplierRepository() *InMemorySupplierRepository {
	return &InMemorySupplierRepository{newTable(func(s Supplier) string { return s.ID }, CopySupplier)}
}

func (r *InMemorySupplierRepository) Get(id string) (Supplier, bool) { return r.rows.get(id) }

func (r *InMemorySupplierRepository) Save(supplier Supplier) { r.rows.save(supplier) }

func (r *InMemorySupplierRepository) List() []Supplier { return r.rows.list() }

type InMemoryPurchaseRepository struct{ rows *table[PurchaseOrder] }

func NewInMemoryPurchaseRepository() *InMemoryPurchaseRepository {
	return &InMemoryPurchaseRepository{newTable(func(p PurchaseOrder) string { return p.ID }, CopyPurchase)}
}

func (r *InMemoryPurchaseRepository) Get(id string) (PurchaseOrder, bool) { return r.rows.get(id) }

func (r *InMemoryPurchaseRepository) Save(order PurchaseOrder) { r.rows.save(order) }

func (r *InMemoryPurchaseRepository) List() []PurchaseOrder { return r.rows.list() }

type InMemoryStockRepository struct {
	levels *table[StockLevel]
	held   *table[Reservation]
	log    []StockMovement
}

func NewInMemoryStockRepository() *InMemoryStockRepository {
	return &InMemoryStockRepository{
		levels: newTable(func(l StockLevel) string { return l.SKU }, CopyLevel),
		held:   newTable(func(r Reservation) string { return r.OrderID }, CopyReservation),
	}
}

func (r *InMemoryStockRepository) Get(sku string) (StockLevel, bool) { return r.levels.get(sku) }

func (r *InMemoryStockRepository) Save(level StockLevel) { r.levels.save(level) }

func (r *InMemoryStockRepository) List() []StockLevel { return r.levels.list() }

func (r *InMemoryStockRepository) Reservation(orderID string) (Reservation, bool) {
	return r.held.get(orderID)
}

func (r *InMemoryStockRepository) Reservations() []Reservation { return r.held.list() }

func (r *InMemoryStockRepository) SaveReservation(reservation Reservation) {
	r.held.save(reservation)
}

func (r *InMemoryStockRepository) RemoveReservation(orderID string) { r.held.remove(orderID) }

func (r *InMemoryStockRepository) AddMovement(movement StockMovement) {
	r.log = append(r.log, movement)
}

func (r *InMemoryStockRepository) Movements() []StockMovement {
	return append([]StockMovement{}, r.log...)
}

type InMemoryAccountRepository struct {
	log []AccountEntry
}

func NewInMemoryAccountRepository() *InMemoryAccountRepository {
	return &InMemoryAccountRepository{}
}

func (r *InMemoryAccountRepository) Add(entry AccountEntry) { r.log = append(r.log, entry) }

func (r *InMemoryAccountRepository) Entries(customerID string) []AccountEntry {
	return slices.DeleteFunc(slices.Clone(r.log), func(e AccountEntry) bool { return e.CustomerID != customerID })
}

type InMemoryEventStore struct {
	log []ShopEvent
}

func NewInMemoryEventStore() *InMemoryEventStore { return &InMemoryEventStore{} }

func (s *InMemoryEventStore) Append(event ShopEvent) { s.log = append(s.log, CopyEvent(event)) }

func (s *InMemoryEventStore) List() []ShopEvent {
	list := []ShopEvent{}
	for _, event := range s.log {
		list = append(list, CopyEvent(event))
	}
	return list
}

// --- The payment gateway ------------------------------------------------------

// InMemoryPaymentGateway is a PaymentGateway in memory: it accepts every
// token but the declined ones, and keeps each charge and each refund.
type InMemoryPaymentGateway struct {
	ids      IDSource
	declined map[string]bool
	payments []Payment
	refunded []Refund
}

func NewInMemoryPaymentGateway(ids IDSource) *InMemoryPaymentGateway {
	return &InMemoryPaymentGateway{ids: ids, declined: map[string]bool{}}
}

func (g *InMemoryPaymentGateway) Decline(token string) { g.declined[token] = true }

func (g *InMemoryPaymentGateway) Charge(token string, amount Cents) (Payment, error) {
	if err := CheckCents(amount, "amount", 1); err != nil {
		return Payment{}, err
	}
	if g.declined[token] {
		return Payment{}, Declined("payment declined")
	}
	payment := Payment{ID: g.ids.Next(Prefix.Payment), Token: token, Amount: amount}
	g.payments = append(g.payments, payment)
	return payment, nil
}

func (g *InMemoryPaymentGateway) Refund(paymentID string) (Refund, error) {
	i := slices.IndexFunc(g.payments, func(p Payment) bool { return p.ID == paymentID })
	if i < 0 {
		return Refund{}, NotFound("payment", paymentID)
	}
	if slices.ContainsFunc(g.refunded, func(r Refund) bool { return r.PaymentID == paymentID }) {
		return Refund{}, Conflict("payment " + paymentID + " is already refunded")
	}
	refund := Refund{PaymentID: paymentID, Amount: g.payments[i].Amount}
	g.refunded = append(g.refunded, refund)
	return refund, nil
}

// RefundPart refunds part of a payment. The refunds of a payment never add up
// to more than its amount.
func (g *InMemoryPaymentGateway) RefundPart(paymentID string, amount Cents) (Refund, error) {
	i := slices.IndexFunc(g.payments, func(p Payment) bool { return p.ID == paymentID })
	if i < 0 {
		return Refund{}, NotFound("payment", paymentID)
	}
	if err := CheckCents(amount, "amount", 1); err != nil {
		return Refund{}, err
	}
	left := g.payments[i].Amount
	for _, refund := range g.refunded {
		if refund.PaymentID == paymentID {
			left -= refund.Amount
		}
	}
	if amount > left {
		return Refund{}, Conflict(fmt.Sprintf("payment %s has %d left to refund", paymentID, left))
	}
	refund := Refund{PaymentID: paymentID, Amount: amount}
	g.refunded = append(g.refunded, refund)
	return refund, nil
}

func (g *InMemoryPaymentGateway) Charges() []Payment { return append([]Payment{}, g.payments...) }

func (g *InMemoryPaymentGateway) Refunds() []Refund { return append([]Refund{}, g.refunded...) }

// Balance gives what the shop holds of the payments: the charges less the
// refunds.
func (g *InMemoryPaymentGateway) Balance() Cents {
	balance := 0
	for _, payment := range g.payments {
		balance += payment.Amount
	}
	for _, refund := range g.refunded {
		balance -= refund.Amount
	}
	return balance
}

// --- The outbox ---------------------------------------------------------------

// InMemoryOutbox is a Notifier in memory: it keeps each message that the
// shop sends, in the order that the shop sent them, instead of sending an
// email.
type InMemoryOutbox struct {
	messages []Message
}

func NewInMemoryOutbox() *InMemoryOutbox { return &InMemoryOutbox{} }

func (o *InMemoryOutbox) Send(message Message) { o.messages = append(o.messages, message) }

func (o *InMemoryOutbox) Sent() []Message { return append([]Message{}, o.messages...) }

// SentTo gives the messages sent to one address.
func (o *InMemoryOutbox) SentTo(email string) []Message {
	return slices.DeleteFunc(o.Sent(), func(m Message) bool { return m.To != email })
}
