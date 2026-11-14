// Payments. The shop charges a payment token at checkout, through a payment
// gateway outside the shop, and refunds the whole payment when an order is
// cancelled. The gateway is behind this interface; adapters/memory.go holds
// the one in memory.

package domain

type Payment struct {
	ID     string
	Token  string
	Amount Cents
}

type Refund struct {
	PaymentID string
	Amount    Cents
}

type PaymentGateway interface {
	Charge(token string, amount Cents) (Payment, error)
	Refund(paymentID string) (Refund, error)
}
