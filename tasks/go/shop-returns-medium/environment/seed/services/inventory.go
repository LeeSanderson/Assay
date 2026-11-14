// The inventory: the stock of each SKU. Stock on hand is either available or
// reserved for an order. A reservation holds stock from checkout until the
// order ships (commit) or is cancelled (release). Each change to the stock on
// hand adds a movement to the log of the store.

package services

import (
	"fmt"
	"slices"

	. "shop/domain"
)

type Inventory struct {
	repository StockRepository
}

func NewInventory(repository StockRepository) *Inventory {
	return &Inventory{repository: repository}
}

// Movements gives the movements of one SKU, oldest first.
func (inv *Inventory) Movements(sku string) []StockMovement {
	return slices.DeleteFunc(inv.repository.Movements(), func(m StockMovement) bool { return m.SKU != sku })
}

// LowStock gives the SKUs whose available stock is below the threshold, in
// SKU order.
func (inv *Inventory) LowStock(threshold int) []StockLevel {
	low := slices.DeleteFunc(inv.repository.List(), func(l StockLevel) bool { return AvailableOf(l) >= threshold })
	slices.SortFunc(low, func(a, b StockLevel) int { return CompareText(a.SKU, b.SKU) })
	return low
}

// Count sets the stock on hand after a count. It cannot go below the
// reserved stock.
func (inv *Inventory) Count(sku string, onHand int) error {
	if err := inv.checkCount(StockLine{SKU: sku, Quantity: onHand}); err != nil {
		return err
	}
	level := inv.Level(sku)
	inv.move(sku, onHand-level.OnHand, "counted")
	level.OnHand = onHand
	inv.repository.Save(level)
	return nil
}

func (inv *Inventory) checkCount(count StockLine) error {
	reserved := inv.Level(count.SKU).Reserved
	return first(Check(count.Quantity >= 0, "a count must be at least 0"),
		Check(count.Quantity >= reserved, fmt.Sprintf("%s has %d reserved", count.SKU, reserved)))
}

// StockTake counts many SKUs at once, all or none: each count must be at
// least the reserved stock of its SKU. It gives the variance of each SKU
// whose count differs from its stock on hand, in the order of the counts.
func (inv *Inventory) StockTake(counts []StockLine) ([]Variance, error) {
	for i, count := range counts {
		twice := slices.ContainsFunc(counts[:i], func(c StockLine) bool { return c.SKU == count.SKU })
		if err := first(Check(count.Quantity >= 0, "a count must be at least 0"),
			Check(!twice, fmt.Sprintf("SKU %s is counted more than once", count.SKU)),
			inv.checkCount(count)); err != nil {
			return nil, err
		}
	}
	variances := []Variance{}
	for _, count := range counts {
		if expected := inv.Level(count.SKU).OnHand; count.Quantity != expected {
			_ = inv.Count(count.SKU, count.Quantity) // checked above
			variances = append(variances, Variance{SKU: count.SKU, Expected: expected, Counted: count.Quantity,
				Difference: count.Quantity - expected})
		}
	}
	return variances, nil
}

// History gives the movements of one SKU with its running stock on hand.
func (inv *Inventory) History(sku string) []BalanceLine {
	return RunningBalance(inv.Movements(sku))
}

// SKUs gives the SKUs that the store holds a level for, in SKU order.
func (inv *Inventory) SKUs() []string {
	skus := []string{}
	for _, level := range inv.repository.List() {
		skus = append(skus, level.SKU)
	}
	slices.SortFunc(skus, CompareText)
	return skus
}

func (inv *Inventory) Level(sku string) StockLevel {
	if level, ok := inv.repository.Get(sku); ok {
		return level
	}
	return EmptyLevel(sku)
}

func (inv *Inventory) Available(sku string) int { return AvailableOf(inv.Level(sku)) }

func (inv *Inventory) Receive(sku string, quantity int) error {
	if err := CheckQuantity(quantity); err != nil {
		return err
	}
	level := inv.Level(sku)
	level.OnHand += quantity
	inv.repository.Save(level)
	inv.move(sku, quantity, "received")
	return nil
}

// WriteOff takes stock that was lost or spoiled out of the available stock.
func (inv *Inventory) WriteOff(sku string, quantity int) error {
	available := inv.Available(sku)
	if err := first(CheckQuantity(quantity), Check(quantity <= available,
		fmt.Sprintf("not enough stock of %s: %d available", sku, available))); err != nil {
		return err
	}
	level := inv.Level(sku)
	level.OnHand -= quantity
	inv.repository.Save(level)
	inv.move(sku, -quantity, "written-off")
	return nil
}

// Reserve reserves every line for the order, or none of them.
func (inv *Inventory) Reserve(orderID string, lines []StockLine) error {
	if _, ok := inv.repository.Reservation(orderID); ok {
		return Conflict(fmt.Sprintf("order %s already has a reservation", orderID))
	}
	for _, line := range lines {
		if err := CheckQuantity(line.Quantity); err != nil {
			return err
		}
	}
	merged := MergeLines(lines)
	for _, line := range merged {
		if available := inv.Available(line.SKU); line.Quantity > available {
			return Invalid(fmt.Sprintf("not enough stock of %s: %d available", line.SKU, available))
		}
	}
	for _, line := range merged {
		level := inv.Level(line.SKU)
		level.Reserved += line.Quantity
		inv.repository.Save(level)
	}
	inv.repository.SaveReservation(Reservation{OrderID: orderID, Lines: merged})
	return nil
}

// holding is the stock of one SKU that an order holds.
type holding = struct {
	OrderID  string
	Quantity int
}

// ReservedFor gives the orders that hold stock of the SKU, with how much
// each holds.
func (inv *Inventory) ReservedFor(sku string) []holding {
	var held []holding
	for _, reservation := range inv.repository.Reservations() {
		for _, line := range reservation.Lines {
			if line.SKU == sku {
				held = append(held, holding{reservation.OrderID, line.Quantity})
			}
		}
	}
	return held
}

// Reserved gives the stock that the order holds, one line for each SKU.
func (inv *Inventory) Reserved(orderID string) []StockLine {
	reservation, _ := inv.repository.Reservation(orderID)
	return reservation.Lines
}

// Release gives the reserved stock of the order back to the available stock.
func (inv *Inventory) Release(orderID string) error {
	lines, err := inv.take(orderID)
	for _, line := range lines {
		level := inv.Level(line.SKU)
		level.Reserved -= line.Quantity
		inv.repository.Save(level)
	}
	return err
}

// Commit takes the reserved stock of the order out of the stock on hand.
func (inv *Inventory) Commit(orderID string) error {
	lines, err := inv.take(orderID)
	for _, line := range lines {
		level := inv.Level(line.SKU)
		level.OnHand -= line.Quantity
		level.Reserved -= line.Quantity
		inv.repository.Save(level)
		inv.move(line.SKU, -line.Quantity, "shipped")
	}
	return err
}

func (inv *Inventory) take(orderID string) ([]StockLine, error) {
	reservation, ok := inv.repository.Reservation(orderID)
	if !ok {
		return nil, Invalid(fmt.Sprintf("order %s has no reservation", orderID))
	}
	inv.repository.RemoveReservation(orderID)
	return reservation.Lines, nil
}

func (inv *Inventory) move(sku string, quantity int, reason string) {
	inv.repository.AddMovement(StockMovement{SKU: sku, Quantity: quantity, Reason: reason})
}
