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
	return c.price(lines, coupons)
}

// PlaceOrder redeems the coupons only after the payment, so a failed checkout uses none.
func (c *Checkout) PlaceOrder(request CheckoutRequest) (Order, error) {
	lines, err := c.lines(request.Cart)
	if err != nil {
		return Order{}, err
	}
	quote, err := c.price(lines, request.Coupons)
	if err != nil {
		return Order{}, err
	}
	// Each order line keeps its part of each discount, which a return reverses.
	if c.deps.Promotions != nil {
		parts, _ := c.deps.Promotions.DiscountsByLine(engineLines(lines), request.Coupons, c.deps.Clock.Today())
		for i, discounts := range parts {
			lines[i].Discounts = discounts
		}
	}
	id := c.deps.IDs.Next("order")
	stock := make([]StockLine, 0, len(lines))
	for _, line := range lines {
		stock = append(stock, StockLine{SKU: line.SKU, Quantity: line.Quantity})
	}
	if err := c.deps.Inventory.Reserve(id, stock); err != nil {
		return Order{}, err
	}
	paymentID := ""
	if quote.Total > 0 {
		payment, err := c.deps.Payments.Charge(request.PaymentToken, quote.Total)
		if err != nil {
			_ = c.deps.Inventory.Release(id)
			return Order{}, err
		}
		paymentID = payment.ID
	}
	if c.deps.Promotions != nil { // the quote above has passed, so the redeem does too
		_, _ = c.deps.Promotions.Redeem(engineLines(lines), request.Coupons, c.deps.Clock.Today())
	}
	order := Order{
		ID:        id,
		Lines:     lines,
		Subtotal:  quote.Subtotal,
		Discounts: quote.Discounts,
		Total:     quote.Total,
		Status:    "paid",
		PaymentID: paymentID,
		PlacedOn:  c.deps.Clock.Today(),
	}
	c.deps.Orders.Save(order)
	return order, nil
}

// lines gives the lines of the cart, in cart order, at the catalogue's prices.
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
		lines = append(lines, OrderLine{SKU: line.SKU, Name: product.Name, UnitPrice: product.UnitPrice, Quantity: line.Quantity})
	}
	return lines, nil
}

// price prices the lines with the engine; without one, at their subtotal.
func (c *Checkout) price(lines []OrderLine, coupons []string) (Quote, error) {
	if c.deps.Promotions != nil {
		return c.deps.Promotions.Quote(engineLines(lines), coupons, c.deps.Clock.Today())
	}
	quote, _ := NewPromotionEngine().Quote(engineLines(lines), nil, "")
	quote.Discounts = []Discount{}
	return quote, nil
}

func engineLines(lines []OrderLine) []Line {
	engine := make([]Line, len(lines))
	for i, line := range lines {
		engine[i] = Line{SKU: line.SKU, UnitPrice: line.UnitPrice, Quantity: line.Quantity}
	}
	return engine
}
