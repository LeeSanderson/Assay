// A product of the catalogue: what the shop sells, under its SKU, at a unit
// price in cents. A discontinued product stays in the catalogue, but is no
// longer on sale.

package domain

import "strings"

type Product struct {
	SKU          string
	Name         string
	UnitPrice    Cents
	Discontinued bool
}

// PriceChange is a change of the price of a product.
type PriceChange struct {
	SKU  string
	From Cents
	To   Cents
}

type ProductRepository interface {
	Get(sku string) (Product, bool)
	Save(product Product)
	List() []Product
}

func CheckSKU(sku string) error { return CheckNotEmpty(sku, "SKU") }

func CheckName(name string) error { return CheckNotEmpty(name, "name") }

func CheckPrice(unitPrice Cents) error {
	return Check(unitPrice >= 1, "unit price must be at least 1")
}

func NewProduct(sku, name string, unitPrice Cents) (Product, error) {
	if err := first(CheckSKU(sku), CheckName(name), CheckPrice(unitPrice)); err != nil {
		return Product{}, err
	}
	return Product{SKU: sku, Name: name, UnitPrice: unitPrice}, nil
}

// ProductRow is one row of a price list, as a supplier sends it: the price
// as text, in units and hundredths.
type ProductRow struct {
	SKU   string
	Name  string
	Price string
}

// ImportResult is what an import of a price list did: the SKUs that it added
// and those whose name or price it changed, in the order of the rows, and
// each row that it rejected, by its number (the first row is 1), with the
// reason.
type ImportResult struct {
	Added    []string
	Updated  []string
	Rejected []rejection
}

// rejection is a row of a price list that an import rejected, and why.
type rejection = struct {
	Row    int
	Reason string
}

// ProductOfRow gives the product that a row describes, or the error of its
// first broken rule.
func ProductOfRow(row ProductRow) (Product, error) {
	price, err := ParseCents(row.Price)
	if err != nil {
		return Product{}, err
	}
	return NewProduct(strings.TrimSpace(row.SKU), strings.TrimSpace(row.Name), price)
}

func CopyProduct(product Product) Product { return product }
