// The cart: the SKUs that a customer wants and how many of each, in the order
// that the customer first added them.

package shop

import (
	"errors"
	"fmt"
)

type CartLine struct {
	SKU      string
	Quantity int
}

type Cart struct {
	items []CartLine
}

func NewCart() *Cart {
	return &Cart{}
}

func (c *Cart) Add(sku string, quantity int) error {
	if err := checkQuantity(quantity); err != nil {
		return err
	}
	if i := c.index(sku); i >= 0 {
		c.items[i].Quantity += quantity
		return nil
	}
	c.items = append(c.items, CartLine{SKU: sku, Quantity: quantity})
	return nil
}

func (c *Cart) SetQuantity(sku string, quantity int) error {
	if err := checkQuantity(quantity); err != nil {
		return err
	}
	i, err := c.line(sku)
	if err != nil {
		return err
	}
	c.items[i].Quantity = quantity
	return nil
}

func (c *Cart) Remove(sku string) error {
	i, err := c.line(sku)
	if err != nil {
		return err
	}
	c.items = append(c.items[:i], c.items[i+1:]...)
	return nil
}

func (c *Cart) Lines() []CartLine {
	return append([]CartLine(nil), c.items...)
}

func (c *Cart) IsEmpty() bool {
	return len(c.items) == 0
}

// ItemCount gives the number of units in the cart, over all its lines.
func (c *Cart) ItemCount() int {
	count := 0
	for _, item := range c.items {
		count += item.Quantity
	}
	return count
}

func (c *Cart) Clear() {
	c.items = nil
}

func (c *Cart) index(sku string) int {
	for i, item := range c.items {
		if item.SKU == sku {
			return i
		}
	}
	return -1
}

func (c *Cart) line(sku string) (int, error) {
	i := c.index(sku)
	if i < 0 {
		return 0, fmt.Errorf("SKU %s is not in the cart", sku)
	}
	return i, nil
}

func checkQuantity(quantity int) error {
	if quantity < 1 {
		return errors.New("quantity must be at least 1")
	}
	return nil
}
