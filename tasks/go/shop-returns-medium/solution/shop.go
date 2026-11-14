// The composition root: the whole shop, wired in memory. It builds each store
// and each service once, puts the recording stores between the services and
// the stores of orders, shipments, invoices and customers, so that the event
// log records their changes, and subscribes the accounts to the order events.
// The services take their stores and collaborators as arguments, so a test
// can also build any one of them on its own.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type ShopOptions struct {
	Today   domain.IsoDate        // the date that the clock starts on
	TaxRate *int                  // in basis points; the standard rate when nil
	Rates   []domain.ShippingRate // the carrier's rates; none when empty
}

// Shop is the whole shop, as CreateShop wires it.
type Shop struct {
	Clock      *adapters.FixedClock
	IDs        *adapters.SequentialIDs
	Payments   *adapters.InMemoryPaymentGateway
	Outbox     *adapters.InMemoryOutbox
	Events     *services.EventLog
	Catalogue  *services.Catalogue
	Inventory  *services.Inventory
	Promotions *services.PromotionEngine
	Customers  *services.Customers
	Accounts   *services.Accounts
	Checkout   *services.Checkout
	Orders     *services.Orders
	Returns    *services.Returns
	Shipping   *services.Shipping
	Invoicing  *services.Invoicing
	Purchasing *services.Purchasing
	Reports    *services.Reports
}

func CreateShop(options ShopOptions) (*Shop, error) {
	clock := adapters.NewFixedClock(options.Today)
	ids := adapters.NewSequentialIDs()
	events := services.NewEventLog(services.EventLogDeps{Store: adapters.NewInMemoryEventStore(), Clock: clock, IDs: ids})

	products := adapters.NewInMemoryProductRepository()
	stock := adapters.NewInMemoryStockRepository()
	orderStore := adapters.NewRecordingOrderRepository(adapters.NewInMemoryOrderRepository(), events)
	shipmentStore := adapters.NewRecordingShipmentRepository(adapters.NewInMemoryShipmentRepository(), events)
	invoiceStore := adapters.NewRecordingInvoiceRepository(adapters.NewInMemoryInvoiceRepository(), events)
	customerStore := adapters.NewRecordingCustomerRepository(adapters.NewInMemoryCustomerRepository(), events)

	shop := &Shop{Clock: clock, IDs: ids, Events: events,
		Payments: adapters.NewInMemoryPaymentGateway(ids), Outbox: adapters.NewInMemoryOutbox(),
		Catalogue: services.NewCatalogue(products), Inventory: services.NewInventory(stock),
		Promotions: services.NewPromotionEngine()}
	shop.Customers = services.NewCustomers(services.CustomersDeps{Repository: customerStore, Clock: clock, IDs: ids})
	shop.Accounts = services.NewAccounts(services.AccountsDeps{Repository: adapters.NewInMemoryAccountRepository(),
		Customers: shop.Customers, Clock: clock, IDs: ids})
	shop.Checkout = services.NewCheckout(services.CheckoutDeps{Catalogue: shop.Catalogue, Inventory: shop.Inventory,
		Orders: orderStore, Payments: shop.Payments, Clock: clock, IDs: ids, Promotions: shop.Promotions,
		Customers: shop.Customers})
	shop.Orders = services.NewOrders(orderStore, shop.Inventory, shop.Payments)
	shop.Returns = services.NewReturns(services.ReturnsDeps{Orders: orderStore, Inventory: shop.Inventory,
		Payments: shop.Payments, Clock: clock, IDs: ids})
	shop.Shipping = services.NewShipping(services.ShippingDeps{Shipments: shipmentStore, Orders: shop.Orders,
		Customers: shop.Customers, Notifier: shop.Outbox, Clock: clock, IDs: ids})
	invoicing, err := services.NewInvoicing(services.InvoicingDeps{Invoices: invoiceStore, Orders: shop.Orders,
		Clock: clock, IDs: ids, TaxRate: options.TaxRate})
	if err != nil {
		return nil, err
	}
	shop.Invoicing = invoicing
	shop.Purchasing = services.NewPurchasing(services.PurchasingDeps{Suppliers: adapters.NewInMemorySupplierRepository(),
		Purchases: adapters.NewInMemoryPurchaseRepository(), Catalogue: shop.Catalogue, Inventory: shop.Inventory,
		Notifier: shop.Outbox, Clock: clock, IDs: ids})
	shop.Reports = services.NewReports(services.ReportsDeps{Orders: orderStore, Products: products, Stock: stock,
		Shipments: shipmentStore, Customers: customerStore})

	// A subscriber cannot fail on an event of the shop's own stores.
	_ = events.Subscribe("order-placed", func(e domain.ShopEvent) { _ = shop.Accounts.OnOrderPlaced(e) })
	_ = events.Subscribe("order-cancelled", func(e domain.ShopEvent) { _ = shop.Accounts.OnOrderCancelled(e) })
	_ = events.Subscribe("order-cancelled", func(e domain.ShopEvent) { _ = shop.Shipping.OnOrderCancelled(e) })
	for _, rate := range options.Rates {
		if err := shop.Shipping.SetRate(rate); err != nil {
			return nil, err
		}
	}
	return shop, nil
}
