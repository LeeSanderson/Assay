package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

// invStock gives an inventory with 10 apples and 3 pears.
func invStock(t *testing.T) *Inventory {
	t.Helper()
	stock := NewInventory(adapters.NewInMemoryStockRepository())
	invOK(t, stock.Receive("apple", 10))
	invOK(t, stock.Receive("pear", 3))
	return stock
}

func invEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := invShow(got), invShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func invShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func invErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func invOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func invLines(pairs ...any) []StockLine {
	lines := []StockLine{}
	for i := 0; i < len(pairs); i += 2 {
		lines = append(lines, StockLine{SKU: pairs[i].(string), Quantity: pairs[i+1].(int)})
	}
	return lines
}

func invSKUs(levels []StockLevel) []string {
	skus := []string{}
	for _, level := range levels {
		skus = append(skus, level.SKU)
	}
	return skus
}

func TestInventory(t *testing.T) {
	t.Run("stock on hand", func(t *testing.T) {
		t.Run("has no stock of a SKU that it has never received", func(t *testing.T) {
			invEq(t, NewInventory(adapters.NewInMemoryStockRepository()).Level("kiwi"),
				StockLevel{SKU: "kiwi", OnHand: 0, Reserved: 0})
		})

		t.Run("receives stock", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Receive("apple", 5))
			invEq(t, stock.Level("apple"), StockLevel{SKU: "apple", OnHand: 15, Reserved: 0})
			invEq(t, stock.Available("apple"), 15)
		})

		t.Run("rejects a received quantity below 1", func(t *testing.T) {
			invErr(t, invStock(t).Receive("apple", 0), "quantity must be at least 1")
		})

		t.Run("writes off stock that is available", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("pear", 2)))
			invOK(t, stock.WriteOff("pear", 1))
			invEq(t, stock.Level("pear"), StockLevel{SKU: "pear", OnHand: 2, Reserved: 2})
			invErr(t, stock.WriteOff("pear", 1), "not enough stock of pear: 0 available")
		})

		t.Run("lists the SKUs that it holds in SKU order", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Receive("fig", 1))
			invEq(t, stock.SKUs(), []string{"apple", "fig", "pear"})
		})
	})

	t.Run("reservations", func(t *testing.T) {
		t.Run("reserves stock for an order", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("apple", 4)))
			invEq(t, stock.Level("apple"), StockLevel{SKU: "apple", OnHand: 10, Reserved: 4})
			invEq(t, stock.Available("apple"), 6)
		})

		t.Run("reserves all the lines of an order or none of them", func(t *testing.T) {
			stock := invStock(t)
			invErr(t, stock.Reserve("order-1", invLines("apple", 2, "pear", 4)),
				"not enough stock of pear: 3 available")
			invEq(t, stock.Available("apple"), 10)
			invEq(t, stock.Available("pear"), 3)
		})

		t.Run("reserves the lines of one SKU together", func(t *testing.T) {
			stock := invStock(t)
			invErr(t, stock.Reserve("order-1", invLines("pear", 2, "pear", 2)),
				"not enough stock of pear: 3 available")
			invOK(t, stock.Reserve("order-2", invLines("apple", 2, "apple", 3)))
			invEq(t, stock.Reserved("order-2"), invLines("apple", 5))
		})

		t.Run("rejects a second reservation for the same order", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("apple", 1)))
			invErr(t, stock.Reserve("order-1", invLines("pear", 1)), "order order-1 already has a reservation")
		})

		t.Run("releases a reservation", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("apple", 4)))
			invOK(t, stock.Release("order-1"))
			invEq(t, stock.Level("apple"), StockLevel{SKU: "apple", OnHand: 10, Reserved: 0})
			invEq(t, stock.Reserved("order-1"), []StockLine{})
		})

		t.Run("commits a reservation when the order ships", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("apple", 4)))
			invOK(t, stock.Commit("order-1"))
			invEq(t, stock.Level("apple"), StockLevel{SKU: "apple", OnHand: 6, Reserved: 0})
		})

		t.Run("rejects a release of an order with no reservation", func(t *testing.T) {
			stock := invStock(t)
			invErr(t, stock.Release("order-9"), "order order-9 has no reservation")
			invErr(t, stock.Commit("order-9"), "order order-9 has no reservation")
		})

		t.Run("lists the orders that hold stock of a SKU", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("apple", 4)))
			invOK(t, stock.Reserve("order-2", invLines("pear", 1, "apple", 2)))
			invEq(t, stock.ReservedFor("apple"), []struct {
				OrderID  string
				Quantity int
			}{{"order-1", 4}, {"order-2", 2}})
		})
	})

	t.Run("counts", func(t *testing.T) {
		t.Run("counts stock but not below the reserved stock", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("apple", 4)))
			invOK(t, stock.Count("apple", 7))
			invEq(t, stock.Level("apple"), StockLevel{SKU: "apple", OnHand: 7, Reserved: 4})
			invErr(t, stock.Count("apple", 3), "apple has 4 reserved")
		})

		t.Run("takes stock of many SKUs and gives the variances", func(t *testing.T) {
			stock := invStock(t)
			variances, err := stock.StockTake(invLines("apple", 8, "pear", 3, "fig", 2))
			invOK(t, err)
			invEq(t, variances, []Variance{
				{SKU: "apple", Expected: 10, Counted: 8, Difference: -2},
				{SKU: "fig", Expected: 0, Counted: 2, Difference: 2},
			})
			invEq(t, stock.Level("fig").OnHand, 2)
		})

		t.Run("changes nothing when one count of a stock take is wrong", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("pear", 2)))
			_, err := stock.StockTake(invLines("apple", 1, "pear", 1))
			invErr(t, err, "pear has 2 reserved")
			_, err = stock.StockTake(invLines("apple", 1, "apple", 2))
			invErr(t, err, "SKU apple is counted more than once")
			invEq(t, stock.Level("apple").OnHand, 10)
		})
	})

	t.Run("movements", func(t *testing.T) {
		t.Run("logs the movements of a SKU", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Reserve("order-1", invLines("apple", 4)))
			invOK(t, stock.Commit("order-1"))
			invOK(t, stock.Count("apple", 5))
			invOK(t, stock.WriteOff("apple", 2))
			invEq(t, stock.Movements("apple"), []StockMovement{
				{SKU: "apple", Quantity: 10, Reason: "received"},
				{SKU: "apple", Quantity: -4, Reason: "shipped"},
				{SKU: "apple", Quantity: -1, Reason: "counted"},
				{SKU: "apple", Quantity: -2, Reason: "written-off"},
			})
		})

		t.Run("gives the history of a SKU with its running stock on hand", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Receive("apple", 2))
			invOK(t, stock.WriteOff("apple", 5))
			balances := []int{}
			for _, line := range stock.History("apple") {
				balances = append(balances, line.Balance)
			}
			invEq(t, balances, []int{10, 12, 7})
		})

		t.Run("lists the SKUs with low stock in SKU order", func(t *testing.T) {
			stock := invStock(t)
			invOK(t, stock.Receive("fig", 1))
			invOK(t, stock.Reserve("order-1", invLines("apple", 8)))
			invEq(t, invSKUs(stock.LowStock(4)), []string{"apple", "fig", "pear"})
			invEq(t, invSKUs(stock.LowStock(2)), []string{"fig"})
		})
	})
}
