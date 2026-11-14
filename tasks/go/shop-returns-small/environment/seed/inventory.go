// The inventory: the stock of each SKU. Stock on hand is either available or
// reserved for an order. A reservation holds stock from checkout until the
// order ships (commit) or is cancelled (release).

package shop

import (
	"fmt"
	"sort"
)

type StockLevel struct {
	SKU      string
	OnHand   int
	Reserved int
}

type StockLine struct {
	SKU      string
	Quantity int
}

// StockMovement is a change to the stock on hand, with its reason:
// "received", "shipped" or "counted" (a stock count that set the stock on
// hand).
type StockMovement struct {
	SKU      string
	Quantity int
	Reason   string
}

type StockRepository interface {
	Get(sku string) (StockLevel, bool)
	Save(level StockLevel)
	List() []StockLevel
}

type InMemoryStockRepository struct {
	levels map[string]StockLevel
}

func NewInMemoryStockRepository() *InMemoryStockRepository {
	return &InMemoryStockRepository{levels: map[string]StockLevel{}}
}

func (r *InMemoryStockRepository) Get(sku string) (StockLevel, bool) {
	level, ok := r.levels[sku]
	return level, ok
}

func (r *InMemoryStockRepository) Save(level StockLevel) {
	r.levels[level.SKU] = level
}

func (r *InMemoryStockRepository) List() []StockLevel {
	list := make([]StockLevel, 0, len(r.levels))
	for _, level := range r.levels {
		list = append(list, level)
	}
	return list
}

type Inventory struct {
	repository   StockRepository
	reservations map[string][]StockLine
	log          []StockMovement
}

func NewInventory(repository StockRepository) *Inventory {
	return &Inventory{repository: repository, reservations: map[string][]StockLine{}}
}

// Movements gives the movements of one SKU, oldest first.
func (inv *Inventory) Movements(sku string) []StockMovement {
	var movements []StockMovement
	for _, movement := range inv.log {
		if movement.SKU == sku {
			movements = append(movements, movement)
		}
	}
	return movements
}

// LowStock gives the SKUs whose available stock is below the threshold, in
// SKU order.
func (inv *Inventory) LowStock(threshold int) []StockLevel {
	var low []StockLevel
	for _, level := range inv.repository.List() {
		if level.OnHand-level.Reserved < threshold {
			low = append(low, level)
		}
	}
	sort.Slice(low, func(i, j int) bool { return low[i].SKU < low[j].SKU })
	return low
}

// Count sets the stock on hand after a count. It cannot go below the
// reserved stock.
func (inv *Inventory) Count(sku string, onHand int) error {
	level := inv.Level(sku)
	if onHand < level.Reserved {
		return fmt.Errorf("%s has %d reserved", sku, level.Reserved)
	}
	inv.log = append(inv.log, StockMovement{SKU: sku, Quantity: onHand - level.OnHand, Reason: "counted"})
	level.OnHand = onHand
	inv.repository.Save(level)
	return nil
}

func (inv *Inventory) Level(sku string) StockLevel {
	if level, ok := inv.repository.Get(sku); ok {
		return level
	}
	return StockLevel{SKU: sku}
}

func (inv *Inventory) Available(sku string) int {
	level := inv.Level(sku)
	return level.OnHand - level.Reserved
}

func (inv *Inventory) Receive(sku string, quantity int) error {
	if err := checkQuantity(quantity); err != nil {
		return err
	}
	level := inv.Level(sku)
	level.OnHand += quantity
	inv.repository.Save(level)
	inv.log = append(inv.log, StockMovement{SKU: sku, Quantity: quantity, Reason: "received"})
	return nil
}

// Reserve reserves every line for the order, or none of them.
func (inv *Inventory) Reserve(orderID string, lines []StockLine) error {
	if _, ok := inv.reservations[orderID]; ok {
		return fmt.Errorf("order %s already has a reservation", orderID)
	}
	for _, line := range lines {
		if err := checkQuantity(line.Quantity); err != nil {
			return err
		}
		if available := inv.Available(line.SKU); line.Quantity > available {
			return fmt.Errorf("not enough stock of %s: %d available", line.SKU, available)
		}
	}
	for _, line := range lines {
		level := inv.Level(line.SKU)
		level.Reserved += line.Quantity
		inv.repository.Save(level)
	}
	inv.reservations[orderID] = append([]StockLine(nil), lines...)
	return nil
}

// Release gives the reserved stock of the order back to the available stock.
func (inv *Inventory) Release(orderID string) error {
	lines, err := inv.take(orderID)
	if err != nil {
		return err
	}
	for _, line := range lines {
		level := inv.Level(line.SKU)
		level.Reserved -= line.Quantity
		inv.repository.Save(level)
	}
	return nil
}

// Commit takes the reserved stock of the order out of the stock on hand.
func (inv *Inventory) Commit(orderID string) error {
	lines, err := inv.take(orderID)
	if err != nil {
		return err
	}
	for _, line := range lines {
		level := inv.Level(line.SKU)
		level.OnHand -= line.Quantity
		level.Reserved -= line.Quantity
		inv.repository.Save(level)
		inv.log = append(inv.log, StockMovement{SKU: line.SKU, Quantity: -line.Quantity, Reason: "shipped"})
	}
	return nil
}

func (inv *Inventory) take(orderID string) ([]StockLine, error) {
	lines, ok := inv.reservations[orderID]
	if !ok {
		return nil, fmt.Errorf("order %s has no reservation", orderID)
	}
	delete(inv.reservations, orderID)
	return lines, nil
}
