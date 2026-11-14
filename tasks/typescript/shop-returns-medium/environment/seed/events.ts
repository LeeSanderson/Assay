// The event log: what happened in the shop, and the stores that record it.

export type { Change, ChangeSink, EventData, EventStore, ShopEvent } from './domain/event.ts'
export { InMemoryEventStore } from './adapters/memory.ts'
export {
  RecordingCustomerRepository,
  RecordingInvoiceRepository,
  RecordingOrderRepository,
  RecordingShipmentRepository,
} from './adapters/recording.ts'
export { eventsAsJsonLines, eventsFromJsonLines } from './adapters/text.ts'
export type { EventCount, EventLogDeps, Subscriber } from './services/event-log.ts'
export { EventLog } from './services/event-log.ts'
