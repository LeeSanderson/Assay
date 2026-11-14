// Customers: the people who registered with the shop. Each has a unique
// email address (in any case) and can keep one delivery address.

package services

import (
	"slices"
	"strings"

	. "shop/domain"
)

type CustomersDeps struct {
	Repository CustomerRepository
	Clock      Clock
	IDs        IDSource
}

type Customers struct {
	deps CustomersDeps
}

func NewCustomers(deps CustomersDeps) *Customers { return &Customers{deps: deps} }

// Register registers a customer, with an address or with none (nil).
func (c *Customers) Register(name, email string, address *Address) (Customer, error) {
	normal := NormaliseEmail(email)
	err := first(CheckNotEmpty(name, "name"), CheckEmail(email), c.checkFree(normal, ""))
	if err == nil && address != nil {
		err = CheckAddress(*address)
	}
	if err != nil {
		return Customer{}, err
	}
	customer := CopyCustomer(Customer{ID: c.deps.IDs.Next(Prefix.Customer), Name: strings.TrimSpace(name),
		Email: normal, Address: address, RegisteredOn: c.deps.Clock.Today()})
	c.deps.Repository.Save(customer)
	return customer, nil
}

func (c *Customers) Customer(id string) (Customer, error) {
	if customer, ok := c.deps.Repository.Get(id); ok {
		return customer, nil
	}
	return Customer{}, NotFound("customer", id)
}

// ByEmail gives the customer with the email address, in any case.
func (c *Customers) ByEmail(email string) (Customer, error) {
	if customer, ok := c.findByEmail(NormaliseEmail(email)); ok {
		return customer, nil
	}
	return Customer{}, NotFound("customer", NormaliseEmail(email))
}

func (c *Customers) Rename(id, name string) (Customer, error) {
	return c.change(id, CheckNotEmpty(name, "name"), func(customer *Customer) {
		customer.Name = strings.TrimSpace(name)
	})
}

func (c *Customers) ChangeEmail(id, email string) (Customer, error) {
	normal := NormaliseEmail(email)
	return c.change(id, first(CheckEmail(email), c.checkFree(normal, id)), func(customer *Customer) {
		customer.Email = normal
	})
}

func (c *Customers) MoveTo(id string, address Address) (Customer, error) {
	return c.change(id, CheckAddress(address), func(customer *Customer) { customer.Address = &address })
}

// Close closes the account of a customer, who keeps its orders but can place
// no more of them.
func (c *Customers) Close(id string) (Customer, error) {
	_, err := c.Open(id)
	return c.change(id, err, func(customer *Customer) { customer.ClosedOn = c.deps.Clock.Today() })
}

// Open gives the customer, if its account is open: `customer <id> is closed`
// if not.
func (c *Customers) Open(id string) (Customer, error) {
	customer, err := c.Customer(id)
	if err == nil && customer.ClosedOn != "" {
		err = WrongState("customer", id, "closed")
	}
	return customer, err
}

// OpenCustomers gives the customers whose accounts are open, in the order
// that they registered.
func (c *Customers) OpenCustomers() []Customer {
	return slices.DeleteFunc(c.deps.Repository.List(), func(customer Customer) bool { return customer.ClosedOn != "" })
}

// AddressOf gives the delivery address of a customer: an error when it has
// none.
func (c *Customers) AddressOf(id string) (Address, error) {
	customer, err := c.Customer(id)
	if err == nil && customer.Address == nil {
		err = Invalid("customer " + id + " has no address")
	}
	if err != nil {
		return Address{}, err
	}
	return *customer.Address, nil
}

// Search gives the customers whose name or email holds the text, in any
// case, in the order that they registered.
func (c *Customers) Search(text string) []Customer {
	wanted := strings.ToLower(text)
	return slices.DeleteFunc(c.deps.Repository.List(), func(customer Customer) bool {
		return !strings.Contains(strings.ToLower(customer.Name), wanted) && !strings.Contains(customer.Email, wanted)
	})
}

// change checks the customer and then the rule, and saves the update.
func (c *Customers) change(id string, rule error, update func(*Customer)) (Customer, error) {
	customer, err := c.Customer(id)
	if err = first(rule, err); err != nil {
		return Customer{}, err
	}
	update(&customer)
	customer = CopyCustomer(customer)
	c.deps.Repository.Save(customer)
	return customer, nil
}

// checkFree checks that no customer but `owner` holds the email address.
func (c *Customers) checkFree(normal, owner string) error {
	if holder, ok := c.findByEmail(normal); ok && holder.ID != owner {
		return Conflict("email " + normal + " is already registered")
	}
	return nil
}

func (c *Customers) findByEmail(normal string) (Customer, bool) {
	list := c.deps.Repository.List()
	i := slices.IndexFunc(list, func(customer Customer) bool { return customer.Email == normal })
	if i < 0 {
		return Customer{}, false
	}
	return list[i], true
}
