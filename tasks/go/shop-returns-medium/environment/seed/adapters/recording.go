// Recording stores: each wraps a store, saves through it, and tells the event
// log of each change that a rule of domain/event.go turns into an event. A
// service that saves through a recording store does not know of the event
// log; the composition root (shop.go) puts the recording stores in place.

package adapters

import . "shop/domain"

type store[T any] interface {
	Get(id string) (T, bool)
	Save(record T)
	List() []T
}

// recording saves, then records the change, if the rule gives one.
type recording[T any] struct {
	inner store[T]
	sink  ChangeSink
	id    func(record T) string
	rule  func(before *T, after T) (Change, bool)
}

func (r *recording[T]) Get(id string) (T, bool) { return r.inner.Get(id) }

func (r *recording[T]) Save(record T) {
	before, found := r.inner.Get(r.id(record))
	r.inner.Save(record)
	held := &before
	if !found {
		held = nil
	}
	if change, ok := r.rule(held, record); ok {
		_, _ = r.sink.Record(change) // the event log takes every change that a rule gives
	}
}

func (r *recording[T]) List() []T { return r.inner.List() }

type RecordingOrderRepository = recording[Order]

func NewRecordingOrderRepository(inner OrderRepository, sink ChangeSink) *RecordingOrderRepository {
	return &recording[Order]{inner, sink, func(o Order) string { return o.ID }, OrderChange}
}

type RecordingShipmentRepository = recording[Shipment]

func NewRecordingShipmentRepository(inner ShipmentRepository, sink ChangeSink) *RecordingShipmentRepository {
	return &recording[Shipment]{inner, sink, func(s Shipment) string { return s.ID }, ShipmentChange}
}

type RecordingInvoiceRepository = recording[Invoice]

func NewRecordingInvoiceRepository(inner InvoiceRepository, sink ChangeSink) *RecordingInvoiceRepository {
	return &recording[Invoice]{inner, sink, func(i Invoice) string { return i.ID }, InvoiceChange}
}

type RecordingCustomerRepository = recording[Customer]

func NewRecordingCustomerRepository(inner CustomerRepository, sink ChangeSink) *RecordingCustomerRepository {
	return &recording[Customer]{inner, sink, func(c Customer) string { return c.ID }, CustomerChange}
}
