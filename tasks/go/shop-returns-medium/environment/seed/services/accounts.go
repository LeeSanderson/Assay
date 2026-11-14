// Accounts: the store credit (in cents) and the loyalty points of each
// customer, as a log of entries. A customer earns one point for each whole
// 100 cents of an order that it places, and loses them again when the order
// is cancelled. The account learns of orders from the event log: the
// composition root (shop.go) hands it the `order-placed` and
// `order-cancelled` events.

package services

import (
	"cmp"
	"fmt"
	"slices"

	. "shop/domain"
)

type AccountsDeps struct {
	Repository AccountRepository
	Customers  *Customers
	Clock      Clock
	IDs        IDSource
}

// CentsPerPoint is the cents of an order that earn one point.
const CentsPerPoint = 100

// PointsPerRedemption is the block of points that a customer trades for
// store credit, at one cent a point.
const PointsPerRedemption = 500

type Accounts struct {
	deps AccountsDeps
}

func NewAccounts(deps AccountsDeps) *Accounts { return &Accounts{deps: deps} }

func (a *Accounts) Credit(customerID string) (Cents, error) {
	entries, err := a.entries(customerID)
	return BalanceOf(entries, "credit"), err
}

func (a *Accounts) Points(customerID string) (int, error) {
	entries, err := a.entries(customerID)
	return BalanceOf(entries, "points"), err
}

func (a *Accounts) Statement(customerID string) (Statement, error) {
	entries, err := a.entries(customerID)
	if err != nil {
		return Statement{}, err
	}
	return Statement{CustomerID: customerID, Credit: BalanceOf(entries, "credit"),
		Points: BalanceOf(entries, "points"), Entries: entries}, nil
}

// creditHolder is a customer who holds store credit, with how much.
type creditHolder = struct {
	CustomerID string
	Credit     Cents
}

// CreditHolders gives the customers who hold store credit, with how much,
// the most first, and by customer id on a tie: what the shop owes in credit.
func (a *Accounts) CreditHolders() []creditHolder {
	var holders []creditHolder
	for _, customer := range a.deps.Customers.Search("") {
		if credit, _ := a.Credit(customer.ID); credit > 0 {
			holders = append(holders, creditHolder{customer.ID, credit})
		}
	}
	slices.SortStableFunc(holders, func(x, y creditHolder) int {
		return cmp.Or(y.Credit-x.Credit, CompareText(x.CustomerID, y.CustomerID))
	})
	return holders
}

// AddCredit gives store credit, as a goodwill gesture or a gift card.
func (a *Accounts) AddCredit(customerID string, amount Cents, reason string) (AccountEntry, error) {
	if err := first(CheckCents(amount, "amount", 1), CheckNotEmpty(reason, "reason")); err != nil {
		return AccountEntry{}, err
	}
	return a.add(customerID, "credit", amount, reason)
}

// UseCredit spends store credit; it cannot take the balance below zero.
func (a *Accounts) UseCredit(customerID string, amount Cents, reason string) (AccountEntry, error) {
	err := first(CheckCents(amount, "amount", 1), CheckNotEmpty(reason, "reason"))
	balance, unknown := a.Credit(customerID)
	if err = first(err, unknown); err == nil && amount > balance {
		err = Invalid(fmt.Sprintf("customer %s has %d store credit", customerID, balance))
	}
	if err != nil {
		return AccountEntry{}, err
	}
	return a.add(customerID, "credit", -amount, reason)
}

// TransferCredit moves store credit from one customer to another, all or
// none.
func (a *Accounts) TransferCredit(from, to string, amount Cents) error {
	err := Check(from != to, "a customer cannot transfer credit to itself")
	if err == nil {
		_, err = a.deps.Customers.Open(to)
	}
	if err == nil {
		_, err = a.UseCredit(from, amount, "transfer to "+to)
	}
	if err == nil {
		_, err = a.add(to, "credit", amount, "transfer from "+from)
	}
	return err
}

// RedeemPoints trades points for store credit, in blocks of
// PointsPerRedemption.
func (a *Accounts) RedeemPoints(customerID string, points int) (AccountEntry, error) {
	err := Check(points > 0 && points%PointsPerRedemption == 0,
		fmt.Sprintf("points must be a multiple of %d", PointsPerRedemption))
	balance, unknown := a.Points(customerID)
	if err = first(err, unknown); err == nil && points > balance {
		err = Invalid(fmt.Sprintf("customer %s has %d points", customerID, balance))
	}
	if err != nil {
		return AccountEntry{}, err
	}
	_, _ = a.add(customerID, "points", -points, "redeemed")
	return a.add(customerID, "credit", points, "points redeemed")
}

// OnOrderPlaced awards the points of a placed order to its customer; a guest
// order earns none.
func (a *Accounts) OnOrderPlaced(event ShopEvent) error {
	customerID, ok := event.Data["customerId"].(string)
	total, _ := event.Data["total"].(int)
	if points := total / CentsPerPoint; ok && points > 0 {
		_, err := a.add(customerID, "points", points, "order "+event.Subject)
		return err
	}
	return nil
}

// OnOrderCancelled takes back the points that a cancelled order earned.
func (a *Accounts) OnOrderCancelled(event ShopEvent) error {
	customerID, ok := event.Data["customerId"].(string)
	if !ok {
		return nil
	}
	reason := "order " + event.Subject
	entries, err := a.entries(customerID)
	for _, entry := range entries {
		if entry.Kind == "points" && entry.Reason == reason && err == nil {
			_, err = a.add(customerID, "points", -entry.Amount, "cancelled "+reason)
		}
	}
	return err
}

func (a *Accounts) add(customerID string, kind EntryKind, amount int, reason string) (AccountEntry, error) {
	if _, err := a.deps.Customers.Customer(customerID); err != nil {
		return AccountEntry{}, err
	}
	entry := AccountEntry{ID: a.deps.IDs.Next(Prefix.Entry), CustomerID: customerID, Kind: kind,
		Amount: amount, Reason: reason, On: a.deps.Clock.Today()}
	a.deps.Repository.Add(entry)
	return entry, nil
}

func (a *Accounts) entries(customerID string) ([]AccountEntry, error) {
	if _, err := a.deps.Customers.Customer(customerID); err != nil {
		return nil, err
	}
	return a.deps.Repository.Entries(customerID), nil
}
