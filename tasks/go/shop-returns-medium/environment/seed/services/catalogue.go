// The catalogue: the products that the shop sells, by SKU, and their prices.

package services

import (
	"cmp"
	"slices"
	"strings"

	. "shop/domain"
)

type Catalogue struct {
	repository ProductRepository
	changes    []PriceChange
}

func NewCatalogue(repository ProductRepository) *Catalogue {
	return &Catalogue{repository: repository}
}

func (c *Catalogue) AddProduct(sku, name string, unitPrice Cents) (Product, error) {
	product, err := NewProduct(sku, name, unitPrice)
	if err != nil {
		return Product{}, err
	}
	if c.Has(sku) {
		return Product{}, Conflict("product " + sku + " already exists")
	}
	c.repository.Save(product)
	return product, nil
}

func (c *Catalogue) Product(sku string) (Product, error) {
	if product, ok := c.repository.Get(sku); ok {
		return product, nil
	}
	return Product{}, NotFound("product", sku)
}

// Has tells whether the catalogue holds the SKU, on sale or not.
func (c *Catalogue) Has(sku string) bool {
	_, ok := c.repository.Get(sku)
	return ok
}

func (c *Catalogue) ChangePrice(sku string, unitPrice Cents) error {
	product, err := c.Product(sku)
	if err = first(err, CheckPrice(unitPrice)); err != nil || unitPrice == product.UnitPrice {
		return err
	}
	c.changes = append(c.changes, PriceChange{SKU: sku, From: product.UnitPrice, To: unitPrice})
	product.UnitPrice = unitPrice
	c.repository.Save(product)
	return nil
}

// PriceHistory gives the price changes of one SKU, oldest first.
func (c *Catalogue) PriceHistory(sku string) ([]PriceChange, error) {
	if _, err := c.Product(sku); err != nil {
		return nil, err
	}
	return slices.DeleteFunc(slices.Clone(c.changes), func(p PriceChange) bool { return p.SKU != sku }), nil
}

// Reprice changes the price of each product on sale by `percent` per cent
// (a negative percent lowers it), rounded down to a whole cent, and never
// below 1 cent; only of the given SKUs, when any are given. It gives the
// products that it changed, in SKU order.
func (c *Catalogue) Reprice(percent int, skus ...string) []Product {
	changed := []Product{}
	for _, product := range c.ActiveProducts() {
		unitPrice := max(1, PercentOf(product.UnitPrice, 100+percent))
		if (len(skus) == 0 || slices.Contains(skus, product.SKU)) && unitPrice != product.UnitPrice {
			_ = c.ChangePrice(product.SKU, unitPrice) // a known product and a valid price
			product.UnitPrice = unitPrice
			changed = append(changed, product)
		}
	}
	return changed
}

// ImportProducts imports a price list: a row with a new SKU adds a product, a
// row with a known SKU sets its name and price, and a broken row is rejected
// and changes nothing. A SKU on two rows is rejected the second time.
func (c *Catalogue) ImportProducts(rows []ProductRow) ImportResult {
	result := ImportResult{Added: []string{}, Updated: []string{}}
	var seen []string
	for i, row := range rows {
		product, err := ProductOfRow(row)
		if err == nil && slices.Contains(seen, product.SKU) {
			err = Conflict("SKU " + product.SKU + " is on more than one row")
		}
		if err != nil {
			result.Rejected = append(result.Rejected, struct {
				Row    int
				Reason string
			}{i + 1, err.Error()})
			continue
		}
		seen = append(seen, product.SKU)
		if known, ok := c.repository.Get(product.SKU); !ok {
			c.repository.Save(product)
			result.Added = append(result.Added, product.SKU)
		} else if known.Name != product.Name || known.UnitPrice != product.UnitPrice {
			_ = c.Rename(product.SKU, product.Name)
			_ = c.ChangePrice(product.SKU, product.UnitPrice)
			result.Updated = append(result.Updated, product.SKU)
		}
	}
	return result
}

func (c *Catalogue) Rename(sku, name string) error {
	product, err := c.Product(sku)
	if err = first(err, CheckName(name)); err == nil {
		product.Name = name
		c.repository.Save(product)
	}
	return err
}

// Search gives the products on sale whose name holds the text, in any case,
// in SKU order.
func (c *Catalogue) Search(text string) []Product {
	wanted := strings.ToLower(text)
	return slices.DeleteFunc(c.ActiveProducts(), func(p Product) bool {
		return !strings.Contains(strings.ToLower(p.Name), wanted)
	})
}

func (c *Catalogue) Discontinue(sku string) error { return c.setDiscontinued(sku, true) }

// Reinstate puts a discontinued product back on sale.
func (c *Catalogue) Reinstate(sku string) error { return c.setDiscontinued(sku, false) }

func (c *Catalogue) setDiscontinued(sku string, discontinued bool) error {
	product, err := c.Product(sku)
	if err == nil {
		product.Discontinued = discontinued
		c.repository.Save(product)
	}
	return err
}

// ActiveProducts gives the products on sale, in SKU order.
func (c *Catalogue) ActiveProducts() []Product {
	active := slices.DeleteFunc(c.repository.List(), func(p Product) bool { return p.Discontinued })
	slices.SortStableFunc(active, func(a, b Product) int { return CompareText(a.SKU, b.SKU) })
	return active
}

// InPriceRange gives the products on sale whose price is from `least` to
// `most`, both included, cheapest first, and in SKU order on a tie.
func (c *Catalogue) InPriceRange(least, most Cents) []Product {
	found := slices.DeleteFunc(c.ActiveProducts(), func(p Product) bool {
		return p.UnitPrice < least || p.UnitPrice > most
	})
	slices.SortStableFunc(found, func(a, b Product) int { return cmp.Compare(a.UnitPrice, b.UnitPrice) })
	return found
}

// first gives the first error that is not nil, so that checks run in order.
func first(errs ...error) error {
	for _, err := range errs {
		if err != nil {
			return err
		}
	}
	return nil
}
