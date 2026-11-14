// The event log: what happened in the shop, oldest first. The recording
// stores (adapters/recording.go) record each change; a part of the shop that
// wants to act on an event subscribes to its type. Subscribers run in the
// order that they subscribed, once the event is in the log.

package services

import (
	"maps"
	"slices"

	. "shop/domain"
)

type EventLogDeps struct {
	Store EventStore
	Clock Clock
	IDs   IDSource
}

type Subscriber func(event ShopEvent)

// EventCount is how many events of a type the log holds.
type EventCount struct {
	Type  string
	Count int
}

type subscription struct {
	eventType  string
	subscriber Subscriber
}

// EventLog is the ChangeSink of the recording stores.
type EventLog struct {
	deps          EventLogDeps
	subscriptions []subscription
}

func NewEventLog(deps EventLogDeps) *EventLog { return &EventLog{deps: deps} }

func (l *EventLog) Record(change Change) (ShopEvent, error) {
	if err := CheckNotEmpty(change.Type, "event type"); err != nil {
		return ShopEvent{}, err
	}
	event := ShopEvent{ID: l.deps.IDs.Next(Prefix.Event), Type: change.Type, Subject: change.Subject,
		On: l.deps.Clock.Today(), Data: maps.Clone(change.Data)}
	l.deps.Store.Append(event)
	for _, s := range l.subscriptions {
		if s.eventType == event.Type {
			s.subscriber(CopyEvent(event))
		}
	}
	return event, nil
}

func (l *EventLog) Subscribe(eventType string, subscriber Subscriber) error {
	err := CheckNotEmpty(eventType, "event type")
	if err == nil {
		l.subscriptions = append(l.subscriptions, subscription{eventType, subscriber})
	}
	return err
}

// Replay hands each event of the type that the log holds to the subscriber,
// oldest first, as if it had subscribed from the start; it gives how many.
func (l *EventLog) Replay(eventType string, subscriber Subscriber) int {
	events := l.OfType(eventType)
	for _, event := range events {
		subscriber(event)
	}
	return len(events)
}

func (l *EventLog) All() []ShopEvent { return l.deps.Store.List() }

func (l *EventLog) OfType(eventType string) []ShopEvent {
	return l.filter(func(event ShopEvent) bool { return event.Type == eventType })
}

// LastOf gives the newest event of the type, if the log holds one.
func (l *EventLog) LastOf(eventType string) (ShopEvent, bool) {
	events := l.OfType(eventType)
	if len(events) == 0 {
		return ShopEvent{}, false
	}
	return events[len(events)-1], true
}

// About gives the events of one record, by its id.
func (l *EventLog) About(subject string) []ShopEvent {
	return l.filter(func(event ShopEvent) bool { return event.Subject == subject })
}

func (l *EventLog) Between(from, to IsoDate) ([]ShopEvent, error) {
	if err := CheckPeriod(from, to); err != nil {
		return nil, err
	}
	return l.filter(func(event ShopEvent) bool { return Within(event.On, from, to) }), nil
}

// After gives the events after the one with the id, for a reader that has
// read up to it.
func (l *EventLog) After(id string) []ShopEvent {
	events := l.All()
	return events[slices.IndexFunc(events, func(event ShopEvent) bool { return event.ID == id })+1:]
}

// Counts gives the number of events of each type, by type.
func (l *EventLog) Counts() []EventCount {
	counts := map[string]int{}
	for _, event := range l.All() {
		counts[event.Type]++
	}
	list := []EventCount{}
	for _, eventType := range slices.Sorted(maps.Keys(counts)) {
		list = append(list, EventCount{eventType, counts[eventType]})
	}
	return list
}

func (l *EventLog) filter(keep func(ShopEvent) bool) []ShopEvent {
	return slices.DeleteFunc(l.All(), func(event ShopEvent) bool { return !keep(event) })
}
