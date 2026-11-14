// Payments: the gateway that charges and refunds payment tokens.

package shop

import (
	"shop/adapters"
	"shop/domain"
)

type (
	Payment                = domain.Payment
	PaymentGateway         = domain.PaymentGateway
	Refund                 = domain.Refund
	InMemoryPaymentGateway = adapters.InMemoryPaymentGateway
)

var (
	NewInMemoryPaymentGateway = adapters.NewInMemoryPaymentGateway
)
