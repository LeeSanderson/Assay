// Stock. The stock on hand of a SKU is either available or reserved for an
// order. A reservation holds stock from checkout until the order ships
// (commit) or is cancelled (release). Each change to the stock on hand is a
// movement, with its reason.

package domain

import (
	"fmt"
	"slices"
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
// `received`, `shipped`, `counted` (a stock count that set the stock on
// hand) or `written-off` (stock that was lost or spoiled).
type StockMovement struct {
	SKU      string
	Quantity int
	Reason   string
}

// Reservation is the stock that an order holds, from its checkout until it
// ships or is cancelled.
type Reservation struct {
	OrderID string
	Lines   []StockLine
}

// StockRepository is the store of the stock: the level of each SKU, the
// reservations of the orders, and the movements, oldest first.
type StockRepository interface {
	Get(sku string) (StockLevel, bool)
	Save(level StockLevel)
	List() []StockLevel
	Reservation(orderID string) (Reservation, bool)
	Reservations() []Reservation // in the order that they were made
	SaveReservation(reservation Reservation)
	RemoveReservation(orderID string)
	AddMovement(movement StockMovement)
	Movements() []StockMovement
}

// Variance is the difference that a stock take found for one SKU: what the
// stock on hand was, what the count found, and the difference (below 0 when
// stock went missing).
type Variance struct {
	SKU        string
	Expected   int
	Counted    int
	Difference int
}

// BalanceLine is one movement with the stock on hand after it.
type BalanceLine struct {
	Quantity int
	Reason   string
	Balance  int
}

// RunningBalance gives the movements of one SKU with the running stock on
// hand, from 0.
func RunningBalance(movements []StockMovement) []BalanceLine {
	lines, balance := []BalanceLine{}, 0
	for _, movement := range movements {
		balance += movement.Quantity
		lines = append(lines, BalanceLine{movement.Quantity, movement.Reason, balance})
	}
	return lines
}

func EmptyLevel(sku string) StockLevel { return StockLevel{SKU: sku} }

func AvailableOf(level StockLevel) int { return level.OnHand - level.Reserved }

// MergeLines gives the stock lines of an order, one for each SKU: the
// quantities of a SKU that is on several lines add up, in the order that
// each SKU first appears.
func MergeLines(lines []StockLine) []StockLine {
	merged := []StockLine{}
	for _, line := range lines {
		i := slices.IndexFunc(merged, func(m StockLine) bool { return m.SKU == line.SKU })
		if i < 0 {
			merged = append(merged, line)
		} else {
			merged[i].Quantity += line.Quantity
		}
	}
	return merged
}

func CheckLevel(level StockLevel) error {
	return Check(level.Reserved >= 0 && level.Reserved <= level.OnHand,
		fmt.Sprintf("%s has a broken level", level.SKU))
}

func CopyLevel(level StockLevel) StockLevel { return level }

func CopyReservation(reservation Reservation) Reservation {
	reservation.Lines = slices.Clone(reservation.Lines)
	return reservation
}
