package shop

import (
	"reflect"
	"testing"
)

// catalogueWantError fails the test unless err is an error with the text want.
func catalogueWantError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

// catalogueMust fails the test on an error.
func catalogueMust(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// catalogueWant fails the test unless got and want are deeply equal.
func catalogueWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func catalogueEmpty() *Catalogue {
	return NewCatalogue(NewInMemoryProductRepository())
}

func catalogueSKUs(products []Product) []string {
	skus := []string{}
	for _, product := range products {
		skus = append(skus, product.SKU)
	}
	return skus
}

func TestCatalogue(t *testing.T) {
	t.Run("adds a product that is on sale", func(t *testing.T) {
		shop := catalogueEmpty()
		product, err := shop.AddProduct("apple", "Apple", 250)
		catalogueMust(t, err)
		catalogueWant(t, product, Product{SKU: "apple", Name: "Apple", UnitPrice: 250})
		got, err := shop.Product("apple")
		catalogueMust(t, err)
		catalogueWant(t, got.UnitPrice, 250)
	})

	t.Run("rejects a product with an empty SKU", func(t *testing.T) {
		_, err := catalogueEmpty().AddProduct(" ", "Apple", 250)
		catalogueWantError(t, err, "SKU must not be empty")
	})

	t.Run("rejects a product with an empty name", func(t *testing.T) {
		_, err := catalogueEmpty().AddProduct("apple", "", 250)
		catalogueWantError(t, err, "name must not be empty")
	})

	t.Run("rejects a unit price below 1", func(t *testing.T) {
		_, err := catalogueEmpty().AddProduct("apple", "Apple", 0)
		catalogueWantError(t, err, "unit price must be at least 1")
	})

	t.Run("rejects a SKU that already exists", func(t *testing.T) {
		shop := catalogueEmpty()
		_, err := shop.AddProduct("apple", "Apple", 250)
		catalogueMust(t, err)
		_, err = shop.AddProduct("apple", "Green apple", 300)
		catalogueWantError(t, err, "product apple already exists")
		got, _ := shop.Product("apple")
		catalogueWant(t, got.Name, "Apple")
	})

	t.Run("rejects an unknown product", func(t *testing.T) {
		_, err := catalogueEmpty().Product("kiwi")
		catalogueWantError(t, err, "unknown product kiwi")
	})

	t.Run("changes the price of a product", func(t *testing.T) {
		shop := catalogueEmpty()
		_, err := shop.AddProduct("apple", "Apple", 250)
		catalogueMust(t, err)
		catalogueMust(t, shop.ChangePrice("apple", 275))
		got, _ := shop.Product("apple")
		catalogueWant(t, got.UnitPrice, 275)
		catalogueWantError(t, shop.ChangePrice("apple", 0), "unit price must be at least 1")
	})

	t.Run("renames a product", func(t *testing.T) {
		shop := catalogueEmpty()
		_, err := shop.AddProduct("apple", "Apple", 250)
		catalogueMust(t, err)
		catalogueMust(t, shop.Rename("apple", "Red apple"))
		got, _ := shop.Product("apple")
		catalogueWant(t, got.Name, "Red apple")
		catalogueWantError(t, shop.Rename("apple", ""), "name must not be empty")
	})

	t.Run("lists the products on sale in SKU order without the discontinued ones", func(t *testing.T) {
		shop := catalogueEmpty()
		for _, p := range []Product{{"pear", "Pear", 1000, false}, {"apple", "Apple", 250, false}, {"fig", "Fig", 400, false}} {
			_, err := shop.AddProduct(p.SKU, p.Name, p.UnitPrice)
			catalogueMust(t, err)
		}
		catalogueMust(t, shop.Discontinue("fig"))
		catalogueWant(t, catalogueSKUs(shop.ActiveProducts()), []string{"apple", "pear"})
		fig, _ := shop.Product("fig")
		catalogueWant(t, fig.Discontinued, true)
	})

	t.Run("searches the names of the products on sale in any case", func(t *testing.T) {
		shop := catalogueEmpty()
		for _, p := range []Product{{"apple", "Apple", 250, false}, {"crab", "Crab apple", 90, false}, {"pear", "Pear", 1000, false}} {
			_, err := shop.AddProduct(p.SKU, p.Name, p.UnitPrice)
			catalogueMust(t, err)
		}
		catalogueWant(t, catalogueSKUs(shop.Search("APPLE")), []string{"apple", "crab"})
	})
}
