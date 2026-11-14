package domain

import (
	"fmt"
	"strings"
	"testing"
)

func shipEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := shipShow(got), shipShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func shipShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func shipErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func shipOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

var shipDomestic = ShippingRate{Zone: "domestic", FirstUnit: 400, PerExtraUnit: 100}

func TestShipment(t *testing.T) {
	t.Run("zones", func(t *testing.T) {
		t.Run("puts the home country, Europe and the rest of the world in their zones", func(t *testing.T) {
			shipEq(t, ZoneOf("GB"), Zone("domestic"))
			shipEq(t, ZoneOf("FR"), Zone("europe"))
			shipEq(t, ZoneOf("US"), Zone("world"))
		})

		t.Run("rejects a rate for an unknown zone or with a broken price", func(t *testing.T) {
			moon, cheap, parcel := shipDomestic, shipDomestic, shipDomestic
			moon.Zone, cheap.FirstUnit, parcel.MaxUnitsPerParcel = "moon", -1, -1
			shipErr(t, CheckRate(moon), "unknown zone moon")
			shipErr(t, CheckRate(cheap), "first unit price must be at least 0")
			// 0 is no limit in Go, so a broken limit is below 0.
			shipErr(t, CheckRate(parcel), "a parcel must take at least 1 unit")
		})
	})

	t.Run("costs", func(t *testing.T) {
		t.Run("charges the first unit and each extra unit", func(t *testing.T) {
			shipEq(t, CostOf(shipDomestic, 1, 500), 400)
			shipEq(t, CostOf(shipDomestic, 4, 500), 700)
		})

		t.Run("sends an order free from the free shipping total", func(t *testing.T) {
			rate := shipDomestic
			rate.FreeFrom = 5000
			shipEq(t, CostOf(rate, 4, 4999), 700)
			shipEq(t, CostOf(rate, 4, 5000), 0)
		})

		t.Run("fills parcels up to the units that a parcel takes, and charges each parcel", func(t *testing.T) {
			rate := shipDomestic
			rate.MaxUnitsPerParcel = 3
			shipEq(t, ParcelsOf(rate, 7), []int{3, 3, 1})
			shipEq(t, ParcelsOf(rate, 6), []int{3, 3})
			shipEq(t, ParcelsOf(shipDomestic, 7), []int{7})
			shipEq(t, CostOf(rate, 7, 500), 1600)
		})
	})

	t.Run("the status of a shipment", func(t *testing.T) {
		shipment := func(status ShipmentStatus) Shipment {
			return Shipment{ID: "shipment-1", OrderID: "order-1",
				Address: Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"},
				Zone:    "domestic", Units: 1, Parcels: 1, Cost: 400, Status: status, CreatedOn: "2026-03-10"}
		}

		t.Run("moves from pending to dispatched to delivered", func(t *testing.T) {
			shipOK(t, CheckNext(shipment("pending"), "dispatched"))
			shipOK(t, CheckNext(shipment("dispatched"), "delivered"))
			shipOK(t, CheckNext(shipment("pending"), "cancelled"))
		})

		t.Run("rejects a move out of order", func(t *testing.T) {
			shipErr(t, CheckNext(shipment("pending"), "delivered"), "shipment shipment-1 is pending")
			shipErr(t, CheckNext(shipment("delivered"), "dispatched"), "shipment shipment-1 is delivered")
			shipErr(t, CheckNext(shipment("dispatched"), "cancelled"), "shipment shipment-1 is dispatched")
		})
	})
}
