// The errors of the shop. Every error that the shop returns on purpose is a
// *ShopError, with a code that says what kind of error it is, and a message
// that says what went wrong in plain words. Callers match on the code; tests
// and people read the message.

package domain

import (
	"errors"
	"fmt"
	"strings"
)

type ErrorCode string

const (
	CodeNotFound ErrorCode = "not-found" // the thing that the caller named does not exist
	CodeInvalid  ErrorCode = "invalid"   // the input breaks a rule of the shop
	CodeConflict ErrorCode = "conflict"  // the thing already exists, or is already done
	CodeState    ErrorCode = "state"     // the thing is in a state that does not allow the action
	CodeDeclined ErrorCode = "declined"  // an outside service said no
)

type ShopError struct {
	Code    ErrorCode
	Message string
}

func (e *ShopError) Error() string { return e.Message }

// NotFound gives `unknown <kind> <id>`, as in `unknown order order-9`.
func NotFound(kind, id string) error {
	return &ShopError{CodeNotFound, fmt.Sprintf("unknown %s %s", kind, id)}
}

func Invalid(message string) error { return &ShopError{CodeInvalid, message} }

func Conflict(message string) error { return &ShopError{CodeConflict, message} }

// WrongState gives `<kind> <id> is <state>`, as in `order order-1 is shipped`.
func WrongState(kind, id, state string) error {
	return &ShopError{CodeState, fmt.Sprintf("%s %s is %s", kind, id, state)}
}

func Declined(message string) error { return &ShopError{CodeDeclined, message} }

// Check checks a rule of the shop: an `invalid` error when it does not hold.
func Check(rule bool, message string) error {
	if !rule {
		return Invalid(message)
	}
	return nil
}

// CheckQuantity checks a count of units, which every part of the shop
// requires to be at least 1.
func CheckQuantity(quantity int) error {
	return Check(quantity >= 1, "quantity must be at least 1")
}

// CheckNotEmpty checks that a name or a code holds more than spaces.
func CheckNotEmpty(text, what string) error {
	return Check(strings.TrimSpace(text) != "", what+" must not be empty")
}

// IsShopError tells whether an error is a ShopError with the code; any code
// when the code is empty.
func IsShopError(err error, code ErrorCode) bool {
	var shop *ShopError
	return errors.As(err, &shop) && (code == "" || shop.Code == code)
}

// first gives the first error that is not nil, so that checks run in order.
func first(errs ...error) error {
	for _, err := range errs {
		if err != nil {
			return err
		}
	}
	return nil
}
