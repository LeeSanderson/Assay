// Payments: the shop charges a payment token at checkout and refunds the
// whole payment when an order is cancelled.

package shop

import (
	"errors"
	"fmt"
)

type Payment struct {
	ID     string
	Token  string
	Amount int
}

type Refund struct {
	PaymentID string
	Amount    int
}

type PaymentGateway interface {
	Charge(token string, amount int) (Payment, error)
	Refund(paymentID string) (Refund, error)
}

// InMemoryPaymentGateway accepts every token but the declined ones, and
// keeps each charge and each refund.
type InMemoryPaymentGateway struct {
	ids      IDSource
	declined map[string]bool
	payments []Payment
	refunded []Refund
}

func NewInMemoryPaymentGateway(ids IDSource) *InMemoryPaymentGateway {
	return &InMemoryPaymentGateway{ids: ids, declined: map[string]bool{}}
}

func (g *InMemoryPaymentGateway) Decline(token string) {
	g.declined[token] = true
}

func (g *InMemoryPaymentGateway) Charge(token string, amount int) (Payment, error) {
	if amount < 1 {
		return Payment{}, errors.New("amount must be at least 1")
	}
	if g.declined[token] {
		return Payment{}, errors.New("payment declined")
	}
	payment := Payment{ID: g.ids.Next("payment"), Token: token, Amount: amount}
	g.payments = append(g.payments, payment)
	return payment, nil
}

func (g *InMemoryPaymentGateway) Refund(paymentID string) (Refund, error) {
	for _, payment := range g.payments {
		if payment.ID != paymentID {
			continue
		}
		for _, refund := range g.refunded {
			if refund.PaymentID == paymentID {
				return Refund{}, fmt.Errorf("payment %s is already refunded", paymentID)
			}
		}
		refund := Refund{PaymentID: paymentID, Amount: payment.Amount}
		g.refunded = append(g.refunded, refund)
		return refund, nil
	}
	return Refund{}, fmt.Errorf("unknown payment %s", paymentID)
}

func (g *InMemoryPaymentGateway) Charges() []Payment {
	return append([]Payment(nil), g.payments...)
}

func (g *InMemoryPaymentGateway) Refunds() []Refund {
	return append([]Refund(nil), g.refunded...)
}
