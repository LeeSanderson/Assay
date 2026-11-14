// Customers and their accounts: store credit and loyalty points.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	AccountEntry               = domain.AccountEntry
	AccountRepository          = domain.AccountRepository
	Address                    = domain.Address
	Customer                   = domain.Customer
	CustomerRepository         = domain.CustomerRepository
	EntryKind                  = domain.EntryKind
	Message                    = domain.Message
	Notifier                   = domain.Notifier
	Statement                  = domain.Statement
	InMemoryAccountRepository  = adapters.InMemoryAccountRepository
	InMemoryCustomerRepository = adapters.InMemoryCustomerRepository
	InMemoryOutbox             = adapters.InMemoryOutbox
	AccountsDeps               = services.AccountsDeps
	Accounts                   = services.Accounts
	CustomersDeps              = services.CustomersDeps
	Customers                  = services.Customers
)

const (
	CentsPerPoint       = services.CentsPerPoint
	PointsPerRedemption = services.PointsPerRedemption
)

var (
	NewInMemoryAccountRepository  = adapters.NewInMemoryAccountRepository
	NewInMemoryCustomerRepository = adapters.NewInMemoryCustomerRepository
	NewInMemoryOutbox             = adapters.NewInMemoryOutbox
	StatementText                 = adapters.StatementText
	NewAccounts                   = services.NewAccounts
	NewCustomers                  = services.NewCustomers
)
