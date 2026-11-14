// Shipping: a paid order goes out in one shipment. Creating a shipment
// prices it by the carrier's rate for the zone of the address; dispatching
// it ships the order (so its stock leaves the inventory) and tells the
// customer; the carrier then delivers it.

package services

import (
	"fmt"
	"slices"

	. "shop/domain"
)

type ShippingDeps struct {
	Shipments ShipmentRepository
	Orders    *Orders
	Customers *Customers
	Notifier  Notifier
	Clock     Clock
	IDs       IDSource
}

type Shipping struct {
	deps  ShippingDeps
	rates map[Zone]ShippingRate
}

func NewShipping(deps ShippingDeps) *Shipping {
	return &Shipping{deps: deps, rates: map[Zone]ShippingRate{}}
}

// SetRate sets the rate of the carrier for a zone, in place of the one it
// had.
func (s *Shipping) SetRate(rate ShippingRate) error {
	err := CheckRate(rate)
	if err == nil {
		s.rates[rate.Zone] = rate
	}
	return err
}

func (s *Shipping) Rate(zone Zone) (ShippingRate, error) {
	rate, ok := s.rates[zone]
	if err := first(CheckZone(zone), Check(ok, fmt.Sprintf("no rate for zone %s", zone))); err != nil {
		return ShippingRate{}, err
	}
	return rate, nil
}

// Quote gives what the carrier would charge to send the order to the
// address.
func (s *Shipping) Quote(orderID string, address Address) (Cents, error) {
	order, err := s.deps.Orders.Order(orderID)
	rate, noRate := s.Rate(ZoneOf(address.Country))
	if err = first(CheckAddress(address), err, noRate); err != nil {
		return 0, err
	}
	return CostOf(rate, UnitsOf(order), order.Total), nil
}

// CreateShipment creates the shipment of a paid order, to the address, or
// else (nil) to the address of the order's customer.
func (s *Shipping) CreateShipment(orderID string, address *Address) (Shipment, error) {
	order, err := s.deps.Orders.CheckPaid(orderID)
	if _, found := s.find(orderID); err == nil && found {
		err = Conflict(fmt.Sprintf("order %s already has a shipment", orderID))
	}
	if err == nil && address == nil {
		var to Address
		to, err = s.addressOf(order)
		address = &to
	}
	if err != nil {
		return Shipment{}, err
	}
	zone := ZoneOf(address.Country)
	rate, err := s.Rate(zone)
	if err = first(CheckAddress(*address), err); err != nil {
		return Shipment{}, err
	}
	units := UnitsOf(order)
	shipment := Shipment{ID: s.deps.IDs.Next(Prefix.Shipment), OrderID: orderID, Address: *address,
		Zone: zone, Units: units, Parcels: len(ParcelsOf(rate, units)),
		Cost: CostOf(rate, units, order.Total), Status: "pending", CreatedOn: s.deps.Clock.Today()}
	s.deps.Shipments.Save(shipment)
	return shipment, nil
}

// Dispatch hands the shipment to the carrier: the order ships, and its
// customer, if it has one, gets a message with the tracking code.
func (s *Shipping) Dispatch(id, trackingCode string) (Shipment, error) {
	shipment, err := s.Shipment(id)
	if err = first(CheckTrackingCode(trackingCode), err, CheckNext(shipment, "dispatched")); err == nil {
		err = s.deps.Orders.Ship(shipment.OrderID)
	}
	if err != nil {
		return Shipment{}, err
	}
	shipment.Status, shipment.TrackingCode, shipment.DispatchedOn = "dispatched", trackingCode, s.deps.Clock.Today()
	s.deps.Shipments.Save(shipment)
	s.notify(shipment)
	return shipment, nil
}

func (s *Shipping) Deliver(id string) (Shipment, error) {
	shipment, err := s.Shipment(id)
	if err = first(err, CheckNext(shipment, "delivered")); err != nil {
		return Shipment{}, err
	}
	shipment.Status, shipment.DeliveredOn = "delivered", s.deps.Clock.Today()
	s.deps.Shipments.Save(shipment)
	return shipment, nil
}

// Cancel cancels a pending shipment; its order stays as it is.
func (s *Shipping) Cancel(id string) (Shipment, error) {
	shipment, err := s.Shipment(id)
	if err = first(err, CheckNext(shipment, "cancelled")); err != nil {
		return Shipment{}, err
	}
	shipment.Status = "cancelled"
	s.deps.Shipments.Save(shipment)
	return shipment, nil
}

// OnOrderCancelled cancels the pending shipment of an order that was
// cancelled, if it has one. The composition root (shop.go) calls it on
// `order-cancelled`.
func (s *Shipping) OnOrderCancelled(event ShopEvent) error {
	if shipment, found := s.find(event.Subject); found && shipment.Status == "pending" {
		_, err := s.Cancel(shipment.ID)
		return err
	}
	return nil
}

func (s *Shipping) Shipment(id string) (Shipment, error) {
	if shipment, ok := s.deps.Shipments.Get(id); ok {
		return shipment, nil
	}
	return Shipment{}, NotFound("shipment", id)
}

// ShipmentOf gives the shipment of an order: an error when it has none.
func (s *Shipping) ShipmentOf(orderID string) (Shipment, error) {
	_, err := s.deps.Orders.Order(orderID)
	shipment, found := s.find(orderID)
	if err == nil && !found {
		err = Invalid(fmt.Sprintf("order %s has no shipment", orderID))
	}
	return shipment, err
}

// Pending gives the shipments not yet dispatched, in the order that they
// were created.
func (s *Shipping) Pending() []Shipment {
	return s.filter(func(shipment Shipment) bool { return shipment.Status == "pending" })
}

// Overdue gives the dispatched shipments that the carrier has not delivered
// more than `days` days after their dispatch, on the date of the clock.
func (s *Shipping) Overdue(days int) []Shipment {
	today := s.deps.Clock.Today()
	return s.filter(func(shipment Shipment) bool {
		return shipment.Status == "dispatched" && DaysBetween(shipment.DispatchedOn, today) > days
	})
}

// DeliveredBetween gives the shipments delivered in the period, in the order
// that they were created.
func (s *Shipping) DeliveredBetween(from, to IsoDate) ([]Shipment, error) {
	if err := CheckPeriod(from, to); err != nil {
		return nil, err
	}
	return s.filter(func(shipment Shipment) bool {
		return shipment.DeliveredOn != "" && Within(shipment.DeliveredOn, from, to)
	}), nil
}

// AverageDeliveryDays gives the days from dispatch to delivery, over the
// delivered shipments, on average and rounded down; 0 when none has been
// delivered.
func (s *Shipping) AverageDeliveryDays() int {
	delivered := s.filter(func(shipment Shipment) bool { return shipment.DeliveredOn != "" })
	if len(delivered) == 0 {
		return 0
	}
	days := 0
	for _, shipment := range delivered {
		days += DaysBetween(shipment.DispatchedOn, shipment.DeliveredOn)
	}
	return days / len(delivered)
}

func (s *Shipping) filter(keep func(Shipment) bool) []Shipment {
	return slices.DeleteFunc(s.deps.Shipments.List(), func(shipment Shipment) bool { return !keep(shipment) })
}

// find gives the shipment of the order that is not cancelled, if it has one.
func (s *Shipping) find(orderID string) (Shipment, bool) {
	found := s.filter(func(shipment Shipment) bool {
		return shipment.OrderID == orderID && shipment.Status != "cancelled"
	})
	if len(found) == 0 {
		return Shipment{}, false
	}
	return found[0], true
}

func (s *Shipping) addressOf(order Order) (Address, error) {
	if order.CustomerID == "" {
		return Address{}, Invalid(fmt.Sprintf("order %s has no address", order.ID))
	}
	return s.deps.Customers.AddressOf(order.CustomerID)
}

func (s *Shipping) notify(shipment Shipment) {
	order, _ := s.deps.Orders.Order(shipment.OrderID)
	customer, err := s.deps.Customers.Customer(order.CustomerID)
	if order.CustomerID == "" || err != nil {
		return
	}
	s.deps.Notifier.Send(Message{To: customer.Email, Subject: fmt.Sprintf("Order %s has shipped", order.ID),
		Body: fmt.Sprintf("Hello %s, your order %s is on its way to %s. Tracking code: %s.",
			customer.Name, order.ID, FormatAddress(shipment.Address), shipment.TrackingCode)})
}
