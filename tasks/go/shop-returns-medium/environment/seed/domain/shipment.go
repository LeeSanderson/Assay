// Shipping. A paid order goes out in one shipment, to an address. The cost
// of a shipment is what the carrier charges the shop, by the zone of the
// address and the number of units; the customer does not pay it, so it is
// not part of the order. A shipment is pending until it is dispatched (the
// order then ships), and then delivered.

package domain

import "slices"

type Zone string // `domestic`, `europe` or `world`

var Zones = []Zone{"domestic", "europe", "world"}

// The shop is in GB. The countries of Europe that the carrier counts as one
// zone, by their two-letter codes.
const home = "GB"

var europe = []string{"AT", "BE", "CH", "DE", "DK", "ES", "FI", "FR", "IE", "IT", "NL", "NO",
	"PL", "PT", "SE"}

// ShippingRate is the price list of the carrier for one zone: a price for
// the first unit, a price for each other unit, and an order total from which
// the shop sends the shipment free, when the zone has one.
type ShippingRate struct {
	Zone              Zone
	FirstUnit         Cents
	PerExtraUnit      Cents
	FreeFrom          Cents // 0 when the zone has none
	MaxUnitsPerParcel int   // 0 for no limit
}

type ShipmentStatus string // `pending`, `dispatched`, `delivered` or `cancelled`

type Shipment struct {
	ID           string
	OrderID      string
	Address      Address
	Zone         Zone
	Units        int
	Parcels      int
	Cost         Cents
	Status       ShipmentStatus
	CreatedOn    IsoDate
	TrackingCode string  // from its dispatch
	DispatchedOn IsoDate // empty until then
	DeliveredOn  IsoDate
}

type ShipmentRepository interface {
	Get(id string) (Shipment, bool)
	Save(shipment Shipment)
	List() []Shipment // in the order that they were created
}

func ZoneOf(country string) Zone {
	if country == home {
		return "domestic"
	}
	if slices.Contains(europe, country) {
		return "europe"
	}
	return "world"
}

func CheckZone(zone Zone) error {
	return Check(slices.Contains(Zones, zone), "unknown zone "+string(zone))
}

func CheckRate(rate ShippingRate) error {
	return first(CheckZone(rate.Zone), CheckCents(rate.FirstUnit, "first unit price", 0),
		CheckCents(rate.PerExtraUnit, "extra unit price", 0),
		CheckCents(rate.FreeFrom, "free shipping total", 0),
		Check(rate.MaxUnitsPerParcel >= 0, "a parcel must take at least 1 unit"))
}

// ParcelsOf gives the units in each parcel of a shipment: full parcels of the
// most units that a parcel takes, then one parcel with the rest. One parcel
// when the rate sets no limit.
func ParcelsOf(rate ShippingRate, units int) []int {
	most := rate.MaxUnitsPerParcel
	if most == 0 || units <= most {
		return []int{units}
	}
	parcels := slices.Repeat([]int{most}, units/most)
	if units%most > 0 {
		parcels = append(parcels, units%most)
	}
	return parcels
}

// CostOf gives what the carrier charges for `units` units, for an order of
// `orderTotal`: each parcel costs the first unit price and the extra unit
// price for each other unit in it.
func CostOf(rate ShippingRate, units int, orderTotal Cents) Cents {
	if rate.FreeFrom > 0 && orderTotal >= rate.FreeFrom {
		return 0
	}
	cost := 0
	for _, inParcel := range ParcelsOf(rate, units) {
		cost += rate.FirstUnit + rate.PerExtraUnit*max(0, inParcel-1)
	}
	return cost
}

// shipmentMoves holds the statuses that a shipment can move to from each
// status. A status that is not here moves nowhere.
var shipmentMoves = map[ShipmentStatus][]ShipmentStatus{
	"pending":    {"dispatched", "cancelled"},
	"dispatched": {"delivered"},
}

// CheckNext checks that the shipment can move to the status: `shipment <id>
// is <status>` when not.
func CheckNext(shipment Shipment, status ShipmentStatus) error {
	if !slices.Contains(shipmentMoves[shipment.Status], status) {
		return WrongState("shipment", shipment.ID, string(shipment.Status))
	}
	return nil
}

func CheckTrackingCode(code string) error { return CheckNotEmpty(code, "tracking code") }

func CopyShipment(shipment Shipment) Shipment { return shipment }
