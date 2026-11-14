// The event log: what happened in the shop, and the stores that record it.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	Change                      = domain.Change
	ChangeSink                  = domain.ChangeSink
	EventData                   = domain.EventData
	EventStore                  = domain.EventStore
	ShopEvent                   = domain.ShopEvent
	InMemoryEventStore          = adapters.InMemoryEventStore
	RecordingCustomerRepository = adapters.RecordingCustomerRepository
	RecordingInvoiceRepository  = adapters.RecordingInvoiceRepository
	RecordingOrderRepository    = adapters.RecordingOrderRepository
	RecordingShipmentRepository = adapters.RecordingShipmentRepository
	EventCount                  = services.EventCount
	EventLogDeps                = services.EventLogDeps
	Subscriber                  = services.Subscriber
	EventLog                    = services.EventLog
)

var (
	NewInMemoryEventStore          = adapters.NewInMemoryEventStore
	NewRecordingCustomerRepository = adapters.NewRecordingCustomerRepository
	NewRecordingInvoiceRepository  = adapters.NewRecordingInvoiceRepository
	NewRecordingOrderRepository    = adapters.NewRecordingOrderRepository
	NewRecordingShipmentRepository = adapters.NewRecordingShipmentRepository
	EventsAsJSONLines              = adapters.EventsAsJSONLines
	EventsFromJSONLines            = adapters.EventsFromJSONLines
	NewEventLog                    = services.NewEventLog
)
