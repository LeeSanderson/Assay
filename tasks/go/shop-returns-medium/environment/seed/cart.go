// The cart: the SKUs that a customer wants (domain/cart.go).

package shop

import "shop/domain"

type (
	CartLine = domain.CartLine
	Cart     = domain.Cart
)

var (
	NewCart = domain.NewCart
)
