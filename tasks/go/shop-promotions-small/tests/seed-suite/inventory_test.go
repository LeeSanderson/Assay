package shop

import (
	"reflect"
	"testing"
)

// inventoryWantError fails the test unless err is an error with the text want.
func inventoryWantError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

// inventoryMust fails the test on an error.
func inventoryMust(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// inventoryWant fails the test unless got and want are deeply equal.
func inventoryWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func inventoryStocked(t *testing.T) *Inventory {
	t.Helper()
	stock := NewInventory(NewInMemoryStockRepository())
	inventoryMust(t, stock.Receive("apple", 10))
	inventoryMust(t, stock.Receive("pear", 3))
	return stock
}

func inventoryLevelSKUs(levels []StockLevel) []string {
	skus := []string{}
	for _, level := range levels {
		skus = append(skus, level.SKU)
	}
	return skus
}

func TestInventory(t *testing.T) {
	t.Run("has no stock of a SKU that it has never received", func(t *testing.T) {
		stock := NewInventory(NewInMemoryStockRepository())
		inventoryWant(t, stock.Level("kiwi"), StockLevel{SKU: "kiwi"})
	})

	t.Run("receives stock", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Receive("apple", 5))
		inventoryWant(t, stock.Level("apple"), StockLevel{"apple", 15, 0})
		inventoryWant(t, stock.Available("apple"), 15)
	})

	t.Run("rejects a received quantity below 1", func(t *testing.T) {
		inventoryWantError(t, inventoryStocked(t).Receive("apple", 0), "quantity must be at least 1")
	})

	t.Run("reserves stock for an order", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Reserve("order-1", []StockLine{{"apple", 4}}))
		inventoryWant(t, stock.Level("apple"), StockLevel{"apple", 10, 4})
		inventoryWant(t, stock.Available("apple"), 6)
	})

	t.Run("reserves all the lines of an order or none of them", func(t *testing.T) {
		stock := inventoryStocked(t)
		err := stock.Reserve("order-1", []StockLine{{"apple", 2}, {"pear", 4}})
		inventoryWantError(t, err, "not enough stock of pear: 3 available")
		inventoryWant(t, stock.Available("apple"), 10)
		inventoryWant(t, stock.Available("pear"), 3)
	})

	t.Run("rejects a second reservation for the same order", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Reserve("order-1", []StockLine{{"apple", 1}}))
		err := stock.Reserve("order-1", []StockLine{{"pear", 1}})
		inventoryWantError(t, err, "order order-1 already has a reservation")
	})

	t.Run("releases a reservation", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Reserve("order-1", []StockLine{{"apple", 4}}))
		inventoryMust(t, stock.Release("order-1"))
		inventoryWant(t, stock.Level("apple"), StockLevel{"apple", 10, 0})
	})

	t.Run("commits a reservation when the order ships", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Reserve("order-1", []StockLine{{"apple", 4}}))
		inventoryMust(t, stock.Commit("order-1"))
		inventoryWant(t, stock.Level("apple"), StockLevel{"apple", 6, 0})
	})

	t.Run("rejects a release of an order with no reservation", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryWantError(t, stock.Release("order-9"), "order order-9 has no reservation")
		inventoryWantError(t, stock.Commit("order-9"), "order order-9 has no reservation")
	})

	t.Run("counts stock but not below the reserved stock", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Reserve("order-1", []StockLine{{"apple", 4}}))
		inventoryMust(t, stock.Count("apple", 7))
		inventoryWant(t, stock.Level("apple"), StockLevel{"apple", 7, 4})
		inventoryWantError(t, stock.Count("apple", 3), "apple has 4 reserved")
	})

	t.Run("logs the movements of a SKU", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Reserve("order-1", []StockLine{{"apple", 4}}))
		inventoryMust(t, stock.Commit("order-1"))
		inventoryMust(t, stock.Count("apple", 5))
		inventoryWant(t, stock.Movements("apple"), []StockMovement{
			{"apple", 10, "received"},
			{"apple", -4, "shipped"},
			{"apple", -1, "counted"},
		})
	})

	t.Run("lists the SKUs with low stock in SKU order", func(t *testing.T) {
		stock := inventoryStocked(t)
		inventoryMust(t, stock.Receive("fig", 1))
		inventoryMust(t, stock.Reserve("order-1", []StockLine{{"apple", 8}}))
		inventoryWant(t, inventoryLevelSKUs(stock.LowStock(4)), []string{"apple", "fig", "pear"})
		inventoryWant(t, inventoryLevelSKUs(stock.LowStock(2)), []string{"fig"})
	})
}
