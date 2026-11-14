// Customers and their accounts. A customer registers once, with a unique
// email address, and can keep a delivery address. Each customer has an
// account, which holds store credit (in cents) and loyalty points. The shop
// writes to customers through a Notifier, which is outside the shop.

package domain

import (
	"fmt"
	"regexp"
	"strings"
)

type Address struct {
	Line1    string
	City     string
	Postcode string
	Country  string // a two-letter country code, as `GB`
}

type Customer struct {
	ID           string
	Name         string
	Email        string
	Address      *Address // nil when the customer keeps none
	RegisteredOn IsoDate
	ClosedOn     IsoDate // a closed customer can no longer place orders
}

type CustomerRepository interface {
	Get(id string) (Customer, bool)
	Save(customer Customer)
	List() []Customer // in the order that they registered
}

// EntryKind is the kind of a change to an account: `credit` (in cents) or
// `points`.
type EntryKind string

type AccountEntry struct {
	ID         string
	CustomerID string
	Kind       EntryKind
	Amount     int // added when above 0, taken when below
	Reason     string
	On         IsoDate
}

type AccountRepository interface {
	Add(entry AccountEntry)
	Entries(customerID string) []AccountEntry // oldest first
}

// Statement is a balance of store credit and points, with each entry that
// made it.
type Statement struct {
	CustomerID string
	Credit     Cents
	Points     int
	Entries    []AccountEntry
}

// Message is a message to a customer.
type Message struct {
	To      string // an email address
	Subject string
	Body    string
}

type Notifier interface {
	Send(message Message)
}

var (
	emailPattern   = regexp.MustCompile(`^[^\s@]+@[^\s@]+\.[^\s@]+$`)
	countryPattern = regexp.MustCompile(`^[A-Z]{2}$`)
)

func NormaliseEmail(email string) string { return strings.ToLower(strings.TrimSpace(email)) }

func CheckEmail(email string) error {
	return Check(emailPattern.MatchString(NormaliseEmail(email)), email+" is not an email address")
}

func CheckAddress(address Address) error {
	return first(CheckNotEmpty(address.Line1, "address line"), CheckNotEmpty(address.City, "city"),
		CheckNotEmpty(address.Postcode, "postcode"),
		Check(countryPattern.MatchString(address.Country), address.Country+" is not a country code"))
}

// BalanceOf gives the balance of one kind over the entries.
func BalanceOf(entries []AccountEntry, kind EntryKind) int {
	balance := 0
	for _, entry := range entries {
		if entry.Kind == kind {
			balance += entry.Amount
		}
	}
	return balance
}

// FormatAddress gives a one-line address, as on a label: `1 High St, Leeds
// LS1 1AA, GB`.
func FormatAddress(address Address) string {
	return fmt.Sprintf("%s, %s %s, %s", address.Line1, address.City, address.Postcode, address.Country)
}

func CopyCustomer(customer Customer) Customer {
	if customer.Address != nil {
		address := *customer.Address
		customer.Address = &address
	}
	return customer
}
