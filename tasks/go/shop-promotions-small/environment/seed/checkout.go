// The checkout: it prices a cart from the catalogue, reserves the stock,
// charges the payment and places the order. A checkout that fails changes
// nothing.

package shop

import (
	"errors"
	"fmt"
)

type CheckoutDeps struct {
	Catalogue  *Catalogue
	Inventory  *Inventory
	Orders     OrderRepository
	Payments   PaymentGateway
	Clock      Clock
	IDs        IDSource
	Promotions *PromotionEngine
}

type CheckoutRequest struct {
	Cart         *Cart
	PaymentToken string
	Coupons      []string
}

type Checkout struct {
	deps CheckoutDeps
}

func NewCheckout(deps CheckoutDeps) *Checkout {
	return &Checkout{deps: deps}
}

// Quote gives the price of the cart, as the checkout would charge it now.
func (c *Checkout) Quote(cart *Cart, coupons []string) (Quote, error) {
	lines, err := c.lines(cart)
	if err != nil {
		return Quote{}, err
	}
	return c.price(lines), nil
}

func (c *Checkout) PlaceOrder(request CheckoutRequest) (Order, error) {
	lines, err := c.lines(request.Cart)
	if err != nil {
		return Order{}, err
	}
	quote := c.price(lines)
	id := c.deps.IDs.Next("order")
	stock := make([]StockLine, 0, len(lines))
	for _, line := range lines {
		stock = append(stock, StockLine{SKU: line.SKU, Quantity: line.Quantity})
	}
	if err := c.deps.Inventory.Reserve(id, stock); err != nil {
		return Order{}, err
	}
	payment, err := c.deps.Payments.Charge(request.PaymentToken, quote.Total)
	if err != nil {
		_ = c.deps.Inventory.Release(id)
		return Order{}, err
	}
	order := Order{
		ID:        id,
		Lines:     lines,
		Subtotal:  quote.Subtotal,
		Discounts: quote.Discounts,
		Total:     quote.Total,
		Status:    "paid",
		PaymentID: payment.ID,
		PlacedOn:  c.deps.Clock.Today(),
	}
	c.deps.Orders.Save(order)
	return order, nil
}

// lines gives the lines of the cart, in cart order, at the prices of the
// catalogue.
func (c *Checkout) lines(cart *Cart) ([]OrderLine, error) {
	if cart.IsEmpty() {
		return nil, errors.New("the cart is empty")
	}
	var lines []OrderLine
	for _, line := range cart.Lines() {
		product, err := c.deps.Catalogue.Product(line.SKU)
		if err != nil {
			return nil, err
		}
		if product.Discontinued {
			return nil, fmt.Errorf("product %s is discontinued", line.SKU)
		}
		lines = append(lines, OrderLine{
			SKU:       line.SKU,
			Name:      product.Name,
			UnitPrice: product.UnitPrice,
			Quantity:  line.Quantity,
		})
	}
	return lines, nil
}

func (c *Checkout) price(lines []OrderLine) Quote {
	subtotal := 0
	for _, line := range lines {
		subtotal += line.UnitPrice * line.Quantity
	}
	return Quote{Subtotal: subtotal, Discounts: []Discount{}, Total: subtotal}
}
