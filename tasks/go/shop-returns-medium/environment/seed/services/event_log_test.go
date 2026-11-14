package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

func elogNew() (*adapters.FixedClock, *EventLog) {
	clock := adapters.NewFixedClock("2026-03-10")
	return clock, NewEventLog(EventLogDeps{Store: adapters.NewInMemoryEventStore(), Clock: clock,
		IDs: adapters.NewSequentialIDs()})
}

// elogRecord records a change with no data.
func elogRecord(t *testing.T, events *EventLog, eventType, subject string) {
	t.Helper()
	elogMust(events.Record(Change{Type: eventType, Subject: subject, Data: EventData{}}))(t)
}

func elogField(events []ShopEvent, field func(ShopEvent) string) []string {
	values := []string{}
	for _, event := range events {
		values = append(values, field(event))
	}
	return values
}

func elogSubject(e ShopEvent) string { return e.Subject }

func elogEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := elogShow(got), elogShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func elogShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func elogErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func elogOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func elogMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestEventLog(t *testing.T) {
	t.Run("recording", func(t *testing.T) {
		t.Run("records a change as an event with an id and the date", func(t *testing.T) {
			_, events := elogNew()
			event := elogMust(events.Record(Change{Type: "order-placed", Subject: "order-1", Data: EventData{"total": 5}}))(t)
			elogEq(t, event, ShopEvent{ID: "event-1", Type: "order-placed", Subject: "order-1", On: "2026-03-10",
				Data: EventData{"total": 5}})
			elogEq(t, events.All(), []ShopEvent{event})
		})

		t.Run("rejects an event with no type", func(t *testing.T) {
			_, events := elogNew()
			_, err := events.Record(Change{Type: "", Subject: "x", Data: EventData{}})
			elogErr(t, err, "event type must not be empty")
		})
	})

	t.Run("reading", func(t *testing.T) {
		t.Run("finds the events by type, by record and by period", func(t *testing.T) {
			clock, events := elogNew()
			elogRecord(t, events, "order-placed", "order-1")
			clock.Set("2026-03-12")
			elogRecord(t, events, "order-shipped", "order-1")
			elogRecord(t, events, "order-placed", "order-2")
			elogEq(t, elogField(events.OfType("order-placed"), elogSubject), []string{"order-1", "order-2"})
			elogEq(t, elogField(events.About("order-1"), func(e ShopEvent) string { return e.Type }),
				[]string{"order-placed", "order-shipped"})
			elogEq(t, elogField(elogMust(events.Between("2026-03-11", "2026-03-31"))(t), func(e ShopEvent) string { return e.ID }),
				[]string{"event-2", "event-3"})
			last, ok := events.LastOf("order-placed")
			elogEq(t, []any{last.Subject, ok}, []any{"order-2", true})
			_, ok = events.LastOf("invoice-issued")
			elogEq(t, ok, false)
		})

		t.Run("gives the events after one that a reader has read", func(t *testing.T) {
			_, events := elogNew()
			for _, subject := range []string{"a", "b", "c"} {
				elogRecord(t, events, "t", subject)
			}
			elogEq(t, elogField(events.After("event-1"), elogSubject), []string{"b", "c"})
			elogEq(t, len(events.After("event-9")), 3)
		})

		t.Run("counts the events of each type, by type", func(t *testing.T) {
			_, events := elogNew()
			elogRecord(t, events, "order-shipped", "o")
			elogRecord(t, events, "order-placed", "o")
			elogRecord(t, events, "order-placed", "p")
			elogEq(t, events.Counts(), []EventCount{{Type: "order-placed", Count: 2}, {Type: "order-shipped", Count: 1}})
		})
	})

	t.Run("subscribers", func(t *testing.T) {
		t.Run("hands each new event of its type to each subscriber, in the order that they subscribed", func(t *testing.T) {
			_, events := elogNew()
			seen := []string{}
			elogOK(t, events.Subscribe("order-placed", func(e ShopEvent) { seen = append(seen, "first "+e.Subject) }))
			elogOK(t, events.Subscribe("order-placed", func(e ShopEvent) { seen = append(seen, "second "+e.Subject) }))
			elogOK(t, events.Subscribe("order-shipped", func(e ShopEvent) { seen = append(seen, "shipped "+e.Subject) }))
			elogRecord(t, events, "order-placed", "order-1")
			elogEq(t, seen, []string{"first order-1", "second order-1"})
		})

		t.Run("has the event in the log before a subscriber runs", func(t *testing.T) {
			_, events := elogNew()
			held := 0
			elogOK(t, events.Subscribe("order-placed", func(ShopEvent) { held = len(events.All()) }))
			elogRecord(t, events, "order-placed", "order-1")
			elogEq(t, held, 1)
		})

		t.Run("replays the events of a type to a new subscriber", func(t *testing.T) {
			_, events := elogNew()
			elogRecord(t, events, "order-placed", "order-1")
			elogRecord(t, events, "order-shipped", "order-1")
			elogRecord(t, events, "order-placed", "order-2")
			var seen []ShopEvent
			elogEq(t, events.Replay("order-placed", func(e ShopEvent) { seen = append(seen, e) }), 2)
			elogEq(t, elogField(seen, elogSubject), []string{"order-1", "order-2"})
		})
	})
}
