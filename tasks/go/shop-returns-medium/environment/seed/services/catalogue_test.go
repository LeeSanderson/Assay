package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

func catNew() *Catalogue { return NewCatalogue(adapters.NewInMemoryProductRepository()) }

func catEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := catShow(got), catShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func catShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func catErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func catOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func catMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func catAdd(t *testing.T, c *Catalogue, sku, name string, price Cents) {
	t.Helper()
	catMust(c.AddProduct(sku, name, price))(t)
}

func catSKUs(products []Product) []string {
	skus := []string{}
	for _, p := range products {
		skus = append(skus, p.SKU)
	}
	return skus
}

func catPrices(products []Product) []string {
	pairs := []string{}
	for _, p := range products {
		pairs = append(pairs, fmt.Sprintf("%s %d", p.SKU, p.UnitPrice))
	}
	return pairs
}

func TestCatalogue(t *testing.T) {
	t.Run("products", func(t *testing.T) {
		t.Run("adds a product that is on sale", func(t *testing.T) {
			shop := catNew()
			catEq(t, catMust(shop.AddProduct("apple", "Apple", 250))(t),
				Product{SKU: "apple", Name: "Apple", UnitPrice: 250, Discontinued: false})
			catEq(t, catMust(shop.Product("apple"))(t).UnitPrice, 250)
			catEq(t, []bool{shop.Has("apple"), shop.Has("kiwi")}, []bool{true, false})
		})

		t.Run("rejects a product with an empty SKU", func(t *testing.T) {
			_, err := catNew().AddProduct(" ", "Apple", 250)
			catErr(t, err, "SKU must not be empty")
		})

		t.Run("rejects a product with an empty name", func(t *testing.T) {
			_, err := catNew().AddProduct("apple", "", 250)
			catErr(t, err, "name must not be empty")
		})

		t.Run("rejects a unit price below 1", func(t *testing.T) {
			_, err := catNew().AddProduct("apple", "Apple", 0)
			catErr(t, err, "unit price must be at least 1")
		})

		t.Run("rejects a SKU that already exists", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "apple", "Apple", 250)
			_, err := shop.AddProduct("apple", "Green apple", 300)
			catErr(t, err, "product apple already exists")
			catEq(t, catMust(shop.Product("apple"))(t).Name, "Apple")
		})

		t.Run("rejects an unknown product", func(t *testing.T) {
			_, err := catNew().Product("kiwi")
			catErr(t, err, "unknown product kiwi")
		})

		t.Run("renames a product", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "apple", "Apple", 250)
			catOK(t, shop.Rename("apple", "Red apple"))
			catEq(t, catMust(shop.Product("apple"))(t).Name, "Red apple")
			catErr(t, shop.Rename("apple", ""), "name must not be empty")
		})
	})

	t.Run("prices", func(t *testing.T) {
		t.Run("changes the price of a product", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "apple", "Apple", 250)
			catOK(t, shop.ChangePrice("apple", 275))
			catEq(t, catMust(shop.Product("apple"))(t).UnitPrice, 275)
			catErr(t, shop.ChangePrice("apple", 0), "unit price must be at least 1")
		})

		t.Run("keeps the history of the prices of a product", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "apple", "Apple", 250)
			catOK(t, shop.ChangePrice("apple", 275))
			catOK(t, shop.ChangePrice("apple", 275))
			catOK(t, shop.ChangePrice("apple", 260))
			catEq(t, catMust(shop.PriceHistory("apple"))(t), []PriceChange{
				{SKU: "apple", From: 250, To: 275},
				{SKU: "apple", From: 275, To: 260},
			})
		})

		t.Run("reprices the products on sale by a percentage, rounded down", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "apple", "Apple", 250)
			catAdd(t, shop, "pear", "Pear", 999)
			catAdd(t, shop, "fig", "Fig", 400)
			catOK(t, shop.Discontinue("fig"))
			catEq(t, catPrices(shop.Reprice(10)), []string{"apple 275", "pear 1098"})
			catEq(t, catMust(shop.Product("fig"))(t).UnitPrice, 400)
			catEq(t, catPrices(shop.Reprice(-50, "apple")), []string{"apple 137"})
		})

		t.Run("never reprices a product below 1 cent", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "pin", "Pin", 1)
			catAdd(t, shop, "nail", "Nail", 3)
			catEq(t, catPrices(shop.Reprice(-90)), []string{"nail 1"})
		})

		t.Run("finds the products on sale in a price range, cheapest first", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "pear", "Pear", 1000)
			catAdd(t, shop, "apple", "Apple", 250)
			catAdd(t, shop, "crab", "Crab apple", 250)
			catAdd(t, shop, "fig", "Fig", 400)
			catEq(t, catSKUs(shop.InPriceRange(250, 400)), []string{"apple", "crab", "fig"})
		})
	})

	t.Run("the range on sale", func(t *testing.T) {
		t.Run("lists the products on sale in SKU order without the discontinued ones", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "pear", "Pear", 1000)
			catAdd(t, shop, "apple", "Apple", 250)
			catAdd(t, shop, "fig", "Fig", 400)
			catOK(t, shop.Discontinue("fig"))
			catEq(t, catSKUs(shop.ActiveProducts()), []string{"apple", "pear"})
			catEq(t, catMust(shop.Product("fig"))(t).Discontinued, true)
		})

		t.Run("puts a discontinued product back on sale", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "fig", "Fig", 400)
			catOK(t, shop.Discontinue("fig"))
			catOK(t, shop.Reinstate("fig"))
			catEq(t, catSKUs(shop.ActiveProducts()), []string{"fig"})
		})

		t.Run("searches the names of the products on sale in any case", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "apple", "Apple", 250)
			catAdd(t, shop, "crab", "Crab apple", 90)
			catAdd(t, shop, "pear", "Pear", 1000)
			catEq(t, catSKUs(shop.Search("APPLE")), []string{"apple", "crab"})
		})
	})

	t.Run("price lists", func(t *testing.T) {
		t.Run("adds the new products and updates the known ones", func(t *testing.T) {
			shop := catNew()
			catAdd(t, shop, "apple", "Apple", 250)
			catAdd(t, shop, "pear", "Pear", 1000)
			result := shop.ImportProducts([]ProductRow{
				{SKU: "fig", Name: "Fig", Price: "4.00"},
				{SKU: "apple", Name: "Apple", Price: "2.75"},
				{SKU: "pear", Name: "Pear", Price: "10.00"},
			})
			catEq(t, result, ImportResult{Added: []string{"fig"}, Updated: []string{"apple"}})
			catEq(t, catMust(shop.Product("apple"))(t).UnitPrice, 275)
			catEq(t, catMust(shop.PriceHistory("apple"))(t), []PriceChange{{SKU: "apple", From: 250, To: 275}})
		})

		t.Run("rejects each broken row by its number and imports the rest", func(t *testing.T) {
			shop := catNew()
			result := shop.ImportProducts([]ProductRow{
				{SKU: "fig", Name: "Fig", Price: "4.00"},
				{SKU: "", Name: "Nothing", Price: "1.00"},
				{SKU: "kiwi", Name: "Kiwi", Price: "free"},
				{SKU: "fig", Name: "Fig again", Price: "5.00"},
			})
			catEq(t, result, ImportResult{
				Added:   []string{"fig"},
				Updated: []string{},
				Rejected: []struct {
					Row    int
					Reason string
				}{
					{2, "SKU must not be empty"},
					{3, "free is not an amount"},
					{4, "SKU fig is on more than one row"},
				},
			})
			catEq(t, catMust(shop.Product("fig"))(t).Name, "Fig")
		})
	})
}
