// The checkout: it prices a cart from the catalogue, reserves the stock,
// charges the payment and places the order. A checkout that fails changes
// nothing.

package services

import . "shop/domain"

type CheckoutDeps struct {
	Catalogue  *Catalogue
	Inventory  *Inventory
	Orders     OrderRepository
	Payments   PaymentGateway
	Clock      Clock
	IDs        IDSource
	Promotions *PromotionEngine // nil for none
	Customers  *Customers       // needed only to place orders for customers
}

type CheckoutRequest struct {
	Cart         *Cart
	PaymentToken string
	Coupons      []string
	CustomerID   string // empty for a guest
}

// CartProblem is a line of a cart that the checkout would reject, and why:
// `unknown product`, `discontinued` or `not enough stock`.
type CartProblem struct {
	SKU       string
	Problem   string
	Available int // with `not enough stock`
}

type Checkout struct {
	deps CheckoutDeps
}

func NewCheckout(deps CheckoutDeps) *Checkout { return &Checkout{deps: deps} }

// Problems gives the problems of a cart, line by line, in cart order: what
// the customer must change before the checkout can place the order.
func (c *Checkout) Problems(cart *Cart) []CartProblem {
	problems := []CartProblem{}
	for _, line := range cart.Lines() {
		product, err := c.deps.Catalogue.Product(line.SKU)
		available := c.deps.Inventory.Available(line.SKU)
		switch {
		case err != nil:
			problems = append(problems, CartProblem{SKU: line.SKU, Problem: "unknown product"})
		case product.Discontinued:
			problems = append(problems, CartProblem{SKU: line.SKU, Problem: "discontinued"})
		case line.Quantity > available:
			problems = append(problems, CartProblem{line.SKU, "not enough stock", available})
		}
	}
	return problems
}

// Fit changes the cart so that the checkout can place it: it removes each
// line of a product that is unknown, discontinued or out of stock, and lowers
// each other line to the stock available. It gives the problems that it
// fixed.
func (c *Checkout) Fit(cart *Cart) []CartProblem {
	problems := c.Problems(cart)
	for _, problem := range problems {
		if problem.Available > 0 {
			_ = cart.SetQuantity(problem.SKU, problem.Available)
		} else {
			_ = cart.Remove(problem.SKU)
		}
	}
	return problems
}

// Quote gives the price of the cart, as the checkout would charge it now.
func (c *Checkout) Quote(cart *Cart, coupons []string) (Quote, error) {
	lines, err := c.lines(cart)
	if err != nil {
		return Quote{}, err
	}
	return c.price(lines, coupons)
}

// Reorder gives a new cart with the lines of an earlier order, for a customer
// who wants to buy the same again. The lines of products that are no longer
// on sale are left out.
func (c *Checkout) Reorder(orderID string) (*Cart, error) {
	order, ok := c.deps.Orders.Get(orderID)
	if !ok {
		return nil, NotFound("order", orderID)
	}
	cart := NewCart()
	for _, line := range order.Lines {
		if product, err := c.deps.Catalogue.Product(line.SKU); err == nil && !product.Discontinued {
			_ = cart.Add(line.SKU, line.Quantity)
		}
	}
	return cart, nil
}

// PlaceOrder redeems the coupons only once the payment has gone through, so a
// checkout that fails uses no coupon.
func (c *Checkout) PlaceOrder(request CheckoutRequest) (Order, error) {
	if request.CustomerID != "" {
		if c.deps.Customers == nil {
			return Order{}, Invalid("this checkout takes no customers")
		}
		if _, err := c.deps.Customers.Open(request.CustomerID); err != nil {
			return Order{}, err
		}
	}
	lines, err := c.lines(request.Cart)
	if err != nil {
		return Order{}, err
	}
	quote, err := c.price(lines, request.Coupons)
	if err != nil {
		return Order{}, err
	}
	id := c.deps.IDs.Next(Prefix.Order)
	stock := []StockLine{}
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
	order := Order{ID: id, Lines: lines, Subtotal: quote.Subtotal, Discounts: quote.Discounts,
		Total: quote.Total, Status: "paid", PaymentID: paymentID, PlacedOn: c.deps.Clock.Today(),
		CustomerID: request.CustomerID}
	c.deps.Orders.Save(order)
	return order, nil
}

// lines gives the lines of the cart, in cart order, at the prices of the
// catalogue.
func (c *Checkout) lines(cart *Cart) ([]OrderLine, error) {
	if cart.IsEmpty() {
		return nil, Invalid("the cart is empty")
	}
	var lines []OrderLine
	for _, line := range cart.Lines() {
		product, err := c.deps.Catalogue.Product(line.SKU)
		if err != nil {
			return nil, err
		}
		if product.Discontinued {
			return nil, Invalid("product " + line.SKU + " is discontinued")
		}
		lines = append(lines, OrderLine{SKU: line.SKU, Name: product.Name, UnitPrice: product.UnitPrice, Quantity: line.Quantity})
	}
	return lines, nil
}

// price prices the lines with the engine; without one, the cart costs its
// subtotal.
func (c *Checkout) price(lines []OrderLine, coupons []string) (Quote, error) {
	if c.deps.Promotions != nil {
		return c.deps.Promotions.Quote(engineLines(lines), coupons, c.deps.Clock.Today())
	}
	if len(coupons) > 0 {
		return Quote{}, Invalid("this checkout takes no coupons")
	}
	quote := Quote{Discounts: []Discount{}}
	for _, line := range lines {
		quote.Subtotal += LineTotal(line)
	}
	quote.Total = quote.Subtotal
	return quote, nil
}

func engineLines(lines []OrderLine) []Line {
	engine := make([]Line, len(lines))
	for i, line := range lines {
		engine[i] = Line{SKU: line.SKU, UnitPrice: line.UnitPrice, Quantity: line.Quantity}
	}
	return engine
}
