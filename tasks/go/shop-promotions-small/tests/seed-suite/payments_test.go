package shop

import (
	"reflect"
	"testing"
)

// paymentsWantError fails the test unless err is an error with the text want.
func paymentsWantError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

// paymentsMust fails the test on an error.
func paymentsMust(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// paymentsWant fails the test unless got and want are deeply equal.
func paymentsWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func paymentsGateway() *InMemoryPaymentGateway {
	return NewInMemoryPaymentGateway(NewSequentialIDs())
}

func TestPayments(t *testing.T) {
	t.Run("charges a token", func(t *testing.T) {
		payments := paymentsGateway()
		payment, err := payments.Charge("card", 1500)
		paymentsMust(t, err)
		paymentsWant(t, payment, Payment{"payment-1", "card", 1500})
		paymentsWant(t, payments.Charges(), []Payment{{"payment-1", "card", 1500}})
	})

	t.Run("rejects an amount below 1", func(t *testing.T) {
		payments := paymentsGateway()
		_, err := payments.Charge("card", 0)
		paymentsWantError(t, err, "amount must be at least 1")
		paymentsWant(t, len(payments.Charges()), 0)
	})

	t.Run("declines a declined token", func(t *testing.T) {
		payments := paymentsGateway()
		payments.Decline("stolen")
		_, err := payments.Charge("stolen", 100)
		paymentsWantError(t, err, "payment declined")
		paymentsWant(t, len(payments.Charges()), 0)
	})

	t.Run("refunds a whole payment once", func(t *testing.T) {
		payments := paymentsGateway()
		payment, err := payments.Charge("card", 1500)
		paymentsMust(t, err)
		refund, err := payments.Refund(payment.ID)
		paymentsMust(t, err)
		paymentsWant(t, refund, Refund{"payment-1", 1500})
		_, err = payments.Refund(payment.ID)
		paymentsWantError(t, err, "payment payment-1 is already refunded")
		paymentsWant(t, payments.Refunds(), []Refund{{"payment-1", 1500}})
	})

	t.Run("rejects a refund of an unknown payment", func(t *testing.T) {
		_, err := paymentsGateway().Refund("payment-9")
		paymentsWantError(t, err, "unknown payment payment-9")
	})
}
