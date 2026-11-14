// The cart: the SKUs that a customer wants and how many of each, in the order
// that the customer first added them.

package domain

import "slices"

type CartLine struct {
	SKU      string
	Quantity int
}

type Cart struct {
	items []CartLine
}

func NewCart() *Cart { return &Cart{} }

func (c *Cart) Add(sku string, quantity int) error {
	if err := CheckQuantity(quantity); err != nil {
		return err
	}
	if i := c.index(sku); i >= 0 {
		c.items[i].Quantity += quantity
	} else {
		c.items = append(c.items, CartLine{SKU: sku, Quantity: quantity})
	}
	return nil
}

func (c *Cart) SetQuantity(sku string, quantity int) error {
	if err := CheckQuantity(quantity); err != nil {
		return err
	}
	i, err := c.line(sku)
	if err == nil {
		c.items[i].Quantity = quantity
	}
	return err
}

func (c *Cart) Remove(sku string) error {
	i, err := c.line(sku)
	if err == nil {
		c.items = slices.Delete(c.items, i, i+1)
	}
	return err
}

func (c *Cart) Lines() []CartLine { return append([]CartLine{}, c.items...) }

func (c *Cart) IsEmpty() bool { return len(c.items) == 0 }

// ItemCount gives the number of units in the cart, over all its lines.
func (c *Cart) ItemCount() int {
	count := 0
	for _, item := range c.items {
		count += item.Quantity
	}
	return count
}

func (c *Cart) Clear() { c.items = nil }

func (c *Cart) index(sku string) int {
	return slices.IndexFunc(c.items, func(item CartLine) bool { return item.SKU == sku })
}

func (c *Cart) line(sku string) (int, error) {
	if i := c.index(sku); i >= 0 {
		return i, nil
	}
	return 0, Invalid("SKU " + sku + " is not in the cart")
}
