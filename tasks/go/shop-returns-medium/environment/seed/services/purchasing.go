// Purchasing: the suppliers of the shop and its purchase orders. A purchase
// order is drafted, filled with lines, and sent, which emails it to the
// supplier; each delivery is received into the inventory. A purchase order
// can be cancelled until anything of it has been received.

package services

import (
	"fmt"
	"maps"
	"slices"
	"strings"

	. "shop/domain"
)

type PurchasingDeps struct {
	Suppliers SupplierRepository
	Purchases PurchaseRepository
	Catalogue *Catalogue
	Inventory *Inventory
	Notifier  Notifier
	Clock     Clock
	IDs       IDSource
}

type Purchasing struct {
	deps PurchasingDeps
}

func NewPurchasing(deps PurchasingDeps) *Purchasing { return &Purchasing{deps: deps} }

func (p *Purchasing) AddSupplier(name, email string, leadTimeDays int) (Supplier, error) {
	if err := CheckSupplier(name, email, leadTimeDays); err != nil {
		return Supplier{}, err
	}
	supplier := Supplier{ID: p.deps.IDs.Next(Prefix.Supplier), Name: name, Email: email, LeadTimeDays: leadTimeDays}
	p.deps.Suppliers.Save(supplier)
	return supplier, nil
}

func (p *Purchasing) Supplier(id string) (Supplier, error) {
	if supplier, ok := p.deps.Suppliers.Get(id); ok {
		return supplier, nil
	}
	return Supplier{}, NotFound("supplier", id)
}

// Draft drafts an empty purchase order to the supplier.
func (p *Purchasing) Draft(supplierID string) (PurchaseOrder, error) {
	if _, err := p.Supplier(supplierID); err != nil {
		return PurchaseOrder{}, err
	}
	return p.save(PurchaseOrder{ID: p.deps.IDs.Next(Prefix.Purchase), SupplierID: supplierID,
		Lines: []PurchaseLine{}, Status: "draft", CreatedOn: p.deps.Clock.Today()}), nil
}

// AddLine adds a line of a product of the catalogue to a draft; a SKU that is
// on the draft already gets the quantity added, at the new unit cost.
func (p *Purchasing) AddLine(id, sku string, quantity int, unitCost Cents) (PurchaseOrder, error) {
	order, err := p.draft(id, CheckPurchaseLine(sku, quantity, unitCost))
	if err == nil {
		_, err = p.deps.Catalogue.Product(sku)
	}
	if err != nil {
		return PurchaseOrder{}, err
	}
	if i := slices.IndexFunc(order.Lines, func(line PurchaseLine) bool { return line.SKU == sku }); i >= 0 {
		order.Lines[i].Quantity += quantity
		order.Lines[i].UnitCost = unitCost
	} else {
		order.Lines = append(order.Lines, PurchaseLine{SKU: sku, Quantity: quantity, UnitCost: unitCost})
	}
	return p.save(order), nil
}

// DraftReorder drafts a purchase order to the supplier with a line for each
// SKU whose available stock, with what is on order, is below `threshold`:
// enough to bring it up to `target`, at the unit cost that `costs` gives for
// the SKU. A SKU with no cost is left out. It gives no draft (nil) when no
// SKU is short.
func (p *Purchasing) DraftReorder(supplierID string, costs map[string]Cents, threshold, target int) (*PurchaseOrder, error) {
	if _, err := p.Supplier(supplierID); err != nil {
		return nil, err
	}
	var order *PurchaseOrder
	for _, sku := range slices.Sorted(maps.Keys(costs)) {
		have := p.deps.Inventory.Available(sku) + p.OnOrder(sku)
		if have >= threshold {
			continue
		}
		if order == nil {
			draft, _ := p.Draft(supplierID) // the supplier is known
			order = &draft
		}
		updated, err := p.AddLine(order.ID, sku, target-have, costs[sku])
		if err != nil {
			return nil, err
		}
		*order = updated
	}
	return order, nil
}

func (p *Purchasing) RemoveLine(id, sku string) (PurchaseOrder, error) {
	order, err := p.draft(id, nil)
	i := slices.IndexFunc(order.Lines, func(line PurchaseLine) bool { return line.SKU == sku })
	if err == nil && i < 0 {
		err = Invalid(fmt.Sprintf("SKU %s is not in purchase %s", sku, id))
	}
	if err != nil {
		return PurchaseOrder{}, err
	}
	order.Lines = slices.Delete(order.Lines, i, i+1)
	return p.save(order), nil
}

// Send sends a draft with at least one line to its supplier, by email, and
// expects it after the lead time of the supplier.
func (p *Purchasing) Send(id string) (PurchaseOrder, error) {
	order, err := p.draft(id, nil)
	if err == nil && len(order.Lines) == 0 {
		err = Invalid(fmt.Sprintf("purchase %s has no lines", id))
	}
	supplier, unknown := p.Supplier(order.SupplierID)
	today := p.deps.Clock.Today()
	expected, broken := AddDays(today, supplier.LeadTimeDays)
	if err = first(err, unknown, broken); err != nil {
		return PurchaseOrder{}, err
	}
	order.Status, order.SentOn, order.ExpectedOn = "sent", today, expected
	var body []string
	for _, line := range order.Lines {
		body = append(body, fmt.Sprintf("%d x %s at %s", line.Quantity, line.SKU, FormatCents(line.UnitCost)))
	}
	body = append(body, "Total: "+FormatCents(CostOfPurchase(order)))
	p.deps.Notifier.Send(Message{To: supplier.Email, Subject: "Purchase order " + id, Body: strings.Join(body, "\n")})
	return p.save(order), nil
}

// Receive receives a delivery against a sent purchase order: each line goes
// into the inventory. A delivery cannot hold more of a SKU than is
// outstanding. The purchase order is received once every unit has come in.
func (p *Purchasing) Receive(id string, delivery []StockLine) (PurchaseOrder, error) {
	order, err := p.Purchase(id)
	err = first(err, CheckPurchaseStatus(order, "sent"))
	for _, item := range delivery {
		i := slices.IndexFunc(order.Lines, func(line PurchaseLine) bool { return line.SKU == item.SKU })
		if err = first(err, CheckQuantity(item.Quantity)); err == nil && i < 0 {
			err = Invalid(fmt.Sprintf("SKU %s is not in purchase %s", item.SKU, id))
		} else if err == nil && item.Quantity > Outstanding(order.Lines[i]) {
			err = Invalid(fmt.Sprintf("%s has %d outstanding", item.SKU, Outstanding(order.Lines[i])))
		} else if err == nil {
			order.Lines[i].Received += item.Quantity
		}
	}
	if err != nil {
		return PurchaseOrder{}, err
	}
	for _, item := range delivery {
		_ = p.deps.Inventory.Receive(item.SKU, item.Quantity) // checked above
	}
	if IsReceived(order) {
		order.Status = "received"
	}
	return p.save(order), nil
}

// ReceiveAll receives every unit that is outstanding on a sent purchase
// order.
func (p *Purchasing) ReceiveAll(id string) (PurchaseOrder, error) {
	order, _ := p.Purchase(id)
	var delivery []StockLine
	for _, line := range order.Lines {
		if Outstanding(line) > 0 {
			delivery = append(delivery, StockLine{SKU: line.SKU, Quantity: Outstanding(line)})
		}
	}
	return p.Receive(id, delivery)
}

// Suppliers gives the suppliers, in the order that they were added.
func (p *Purchasing) Suppliers() []Supplier { return p.deps.Suppliers.List() }

func (p *Purchasing) Cancel(id string) (PurchaseOrder, error) {
	order, err := p.Purchase(id)
	if err == nil && order.Status != "draft" && order.Status != "sent" {
		err = WrongState("purchase", id, string(order.Status))
	}
	if err == nil && slices.ContainsFunc(order.Lines, func(line PurchaseLine) bool { return line.Received > 0 }) {
		err = Invalid(fmt.Sprintf("purchase %s has been received in part", id))
	}
	if err != nil {
		return PurchaseOrder{}, err
	}
	order.Status = "cancelled"
	return p.save(order), nil
}

func (p *Purchasing) Purchase(id string) (PurchaseOrder, error) {
	if order, ok := p.deps.Purchases.Get(id); ok {
		return order, nil
	}
	return PurchaseOrder{}, NotFound("purchase", id)
}

// OnOrder gives the units of a SKU that are on sent purchase orders and have
// not come in.
func (p *Purchasing) OnOrder(sku string) int {
	units := 0
	for _, order := range p.deps.Purchases.List() {
		for _, line := range order.Lines {
			if order.Status == "sent" && line.SKU == sku {
				units += Outstanding(line)
			}
		}
	}
	return units
}

// Late gives the sent purchase orders that were expected before the date.
func (p *Purchasing) Late(date IsoDate) []PurchaseOrder {
	return slices.DeleteFunc(p.deps.Purchases.List(), func(order PurchaseOrder) bool {
		return order.Status != "sent" || order.ExpectedOn == "" || order.ExpectedOn >= date
	})
}

// SpendWith gives what the shop has spent with a supplier, over its purchase
// orders that were not cancelled, for every unit ordered.
func (p *Purchasing) SpendWith(supplierID string) (Cents, error) {
	_, err := p.Supplier(supplierID)
	spent := 0
	for _, order := range p.deps.Purchases.List() {
		if order.SupplierID == supplierID && order.Status != "cancelled" {
			spent += CostOfPurchase(order)
		}
	}
	return spent, err
}

// draft gives the purchase order, after the rule, if it is a draft.
func (p *Purchasing) draft(id string, rule error) (PurchaseOrder, error) {
	order, err := p.Purchase(id)
	if err = first(rule, err, CheckPurchaseStatus(order, "draft")); err != nil {
		return PurchaseOrder{}, err
	}
	return order, nil
}

func (p *Purchasing) save(order PurchaseOrder) PurchaseOrder {
	p.deps.Purchases.Save(order)
	return order
}
