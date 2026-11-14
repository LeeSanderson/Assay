// The checkout: it prices a cart, reserves the stock, charges the payment
// and places the order.

package shop

import "shop/services"

type (
	CartProblem     = services.CartProblem
	CheckoutDeps    = services.CheckoutDeps
	CheckoutRequest = services.CheckoutRequest
	Checkout        = services.Checkout
)

var (
	NewCheckout = services.NewCheckout
)
