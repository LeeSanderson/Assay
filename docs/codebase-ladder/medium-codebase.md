# The medium codebase

The medium codebase is the seed of rung E of the codebase ladder (PRD section 20, issue #85). It is the small codebase of rung D grown into an order and inventory service in layers. This note describes its design, so that the Go port (issue #86) can follow it file for file, and so that the pack of rung E (issue #87) knows what it builds on.

- The TypeScript codebase: `tasks/typescript/shop-returns-medium/environment/seed/`, with its `Dockerfile` beside it (the same as rung D's).
- The Go port (issue #86): `tasks/go/shop-returns-medium/environment/seed/`, with rung D's Go `Dockerfile`. It is described in "The Go port" below.
- `tests/test_medium_codebase.py` checks the codebase: the size ranges, the layers, the root entry points, the seed suite in the pinned image, the feature tests of M (they pass) and the feature tests of X (they fail). `tests/task_packs.py` lists it in `MEDIUM_CODEBASES` until the pack of rung E moves it into `CODEBASE_PACKS`.

## What it holds

The small codebase (catalogue, inventory, cart, orders, payments, checkout) and the promotions engine, written to the specification of M, with these areas added:

- **Customers and accounts.** Customers register with a unique email address and can keep an address and close their account. Each account holds store credit (cents) and loyalty points (one point for each whole 100 cents of an order, taken back when the order is cancelled).
- **Shipping.** One shipment for each paid order, priced by the carrier's rate for the zone of the address (domestic, Europe, world) and split into parcels. Dispatching a shipment ships the order and emails the customer.
- **Invoices.** One invoice for each order that is not cancelled, numbered `INV-000001` in the order of issue, with the tax that the total includes.
- **Purchasing.** Suppliers and purchase orders, which bring stock into the inventory.
- **The event log.** What happened to orders, shipments, invoices and customers.
- **Reports.** Sales, promotions, customers, stock, shipping and margin.

It has no returns, no refunds of part of a payment and no credit notes: those are X, the feature of rungs D and E.

## Layers

| Layer | Folder | What it holds | What it imports |
|---|---|---|---|
| Domain | `domain/` | The records (plain data), the rules of the shop as pure functions, and the interfaces of storage and of the services outside the shop (the ports) | Only the domain |
| Services | `services/` | One class for each area of the shop. A service reads and writes records through the ports, and calls the domain for the rules | The domain and other services |
| Adapters | `adapters/` | The ports in memory (each store, the payment gateway, the outbox, the clock, the ids), the recording stores, and the text and CSV formats | The domain and other adapters |
| Root | the repository root | The entry points: one module for each area, which re-exports its names from the layers, and `shop.ts`, the composition root | Any layer |

The tests check these imports (`test_each_layer_imports_only_the_layers_below_it`). Each test file sits beside the module that it tests, and the seed suite has a test file for each domain, service and adapter module, and for `shop.ts`.

The root modules keep the entry points of the small codebase, so that the feature tests of M and X run unchanged in the repository root: `cart.ts`, `catalogue.ts`, `checkout.ts`, `clock.ts`, `inventory.ts`, `orders.ts`, `payments.ts`, `promotions.ts` and `receipt.ts` export every name that rung D's modules of the same name exported, with the same constructors (`new Catalogue(repository)`, `new Inventory(repository)`, `new Orders(repository, inventory, payments)`, `new Checkout(deps)`, `new PromotionEngine()`, `new InMemoryPaymentGateway(ids)`). Results are plain records: amounts are numbers of cents and ids are strings, and the records that the feature tests compare whole (`Product`, `OrderLine`, `StockLevel`, `StockMovement`, `Payment`, `Refund`, `Quote`, `Discount`) have the fields of rung D and no more. X adds `returns.ts` at the root.

### Events

The services do not write events. `shop.ts` puts a recording store (`adapters/recording.ts`) between the services and the stores of orders, shipments, invoices and customers. A recording store saves through the store that it wraps, compares the new record with the one that it held, and a rule of `domain/event.ts` turns the change into an event (`order-placed`, `order-<status>`, `shipment-created`, `shipment-<status>`, `invoice-issued`, `customer-registered`, `customer-updated`, `customer-closed`) or into none. The event log (`services/event-log.ts`) gives each event an id and the date, appends it, and hands it to the subscribers of its type. `shop.ts` subscribes the accounts to `order-placed` and `order-cancelled` (loyalty points), and shipping to `order-cancelled` (it cancels a pending shipment). The constructors of the small codebase take no event log, so this design adds events without a change to them.

### Storage and configuration

Every kind of record has a store behind an interface in the domain (`ProductRepository`, `StockRepository`, `OrderRepository`, and so on), with one adapter in memory in `adapters/memory.ts`. A store keeps copies: what it gives back, and what it saves, is a copy. The stock store also holds the reservations and the movements, so that `new Inventory(repository)` keeps its one argument. The promotions engine and the shipping rates are configuration, held in memory by their service.

Services of the small codebase keep their constructors. Services that the medium codebase adds take one `deps` object (`CustomersDeps`, `ShippingDeps`, and so on), as `Checkout` does. An optional collaborator is an optional field of `deps` (`CheckoutDeps.promotions`, `CheckoutDeps.customers`).

## Conventions

### Errors

- Every error that the shop throws on purpose is a `ShopError` (`domain/errors.ts`), which extends `Error`, with a `code` (`not-found`, `invalid`, `conflict`, `state`, `declined`) and a message in plain words.
- The helpers make the messages the same everywhere: `notFound(kind, id)` gives `unknown <kind> <id>`, and `wrongState(kind, id, state)` gives `<kind> <id> is <state>`. `invalid`, `conflict` and `declined` take the message. `check(rule, message)` throws an `invalid` error when the rule does not hold.
- `checkQuantity` (`quantity must be at least 1`), `checkNotEmpty` (`<what> must not be empty`) and `checkCents` (`<what> must be at least <n>`) are the shared checks.
- The messages of the small codebase and of M are unchanged; the feature tests check them.
- A failed action changes nothing: a service checks everything before its first write.

### Identifiers

- Every record that the shop creates gets its id from an `IdSource` (`domain/ids.ts`) as `<prefix>-<n>`, with one count for each prefix. `PREFIX` names the prefix of each kind of record (`order`, `payment`, `customer`, `shipment`, `invoice`, `event`, `entry`, `supplier`, `purchase`). `IdSource.next` takes any string, so that a new kind of record (X's `credit`) needs no change to it.
- A product's id is its SKU, which the caller gives.
- Invoices also have a number, `INV-` and six digits, with no gaps.
- `compareText` is the one order of SKUs, codes and ids in lists (by UTF-16 code units, as `<` compares strings); `compareIds` orders ids of one kind by their number.
- Dates are `IsoDate` strings, `YYYY-MM-DD`, compared as strings; today comes from a `Clock`, never from the system.

### Money

- Every amount is a whole number of cents in a plain number, of one currency (`Cents` in `domain/money.ts`). There are no money objects, so the feature tests read plain cents back.
- Every division of money is in `domain/money.ts` and rounds down: `percentOf`, `shareOf`, `includedTax`, `allocate` (which gives the cents that the rounding leaves over to the first parts), `takeInOrder`.
- `formatCents` shows `12.34`, `formatMoney` shows `£1,234.56`, and `parseCents` reads `12.34` back.
- Prices include tax. An invoice shows the tax that its total includes, at a rate in basis points (2000 is 20%).

### Status

Orders and shipments move through their statuses by a table of the moves that each status allows (`moveTo` in `domain/order.ts`, `checkNext` in `domain/shipment.ts`). A status that is not in the table moves nowhere, so a new status (X's `returned`) needs no change to the table to be final, and no change makes the code fail to compile.

## Files

Lines are the non-blank lines of production code. The TypeScript total is 4,099 lines in 49 files; the seed suite is 33 test files and 291 tests (`it`), 373 cases with the 82 `describe` groups (the count that the size range checks).

| File | Lines | What it holds |
|---|---|---|
| `domain/errors.ts` | 55 | `ShopError`, the error codes and the shared checks |
| `domain/money.ts` | 105 | `Cents` and every division, format and parse of money |
| `domain/ids.ts` | 38 | `IdSource`, `PREFIX`, `compareIds`, `compareText` |
| `domain/dates.ts` | 77 | `IsoDate`, `Clock`, date arithmetic, periods, months, weekdays |
| `domain/product.ts` | 61 | `Product`, `ProductRepository`, the price list rows |
| `domain/stock.ts` | 93 | `StockLevel`, `StockMovement`, `Reservation`, `StockRepository`, variances |
| `domain/cart.ts` | 47 | `Cart` |
| `domain/order.ts` | 101 | `Order`, `OrderStatus`, `OrderRepository`, the status table, `OrderFilter` |
| `domain/promotion.ts` | 209 | The types of M, validation, precedence, pricing and its explanation |
| `domain/payment.ts` | 18 | `Payment`, `Refund`, `PaymentGateway` |
| `domain/customer.ts` | 86 | `Customer`, `Address`, `AccountEntry`, the account and customer stores, `Notifier` |
| `domain/shipment.ts` | 115 | `Shipment`, zones, rates, parcels and costs, the status table |
| `domain/invoice.ts` | 80 | `Invoice`, its number, and the invoice of an order |
| `domain/purchase.ts` | 78 | `Supplier`, `PurchaseOrder` and their stores |
| `domain/event.ts` | 91 | `ShopEvent`, `EventStore`, `ChangeSink`, the rules that turn changes into events |
| `domain/report.ts` | 219 | The figures of the reports, as pure functions |
| `services/catalogue.ts` | 130 | `Catalogue`: products, prices, price history, repricing, price list import |
| `services/inventory.ts` | 167 | `Inventory`: stock, reservations, counts, stock takes, write-offs |
| `services/promotion-engine.ts` | 138 | `PromotionEngine`: M's engine, coupons, explanations |
| `services/checkout.ts` | 176 | `Checkout`: quotes, orders, customers, cart problems, reorders |
| `services/orders.ts` | 111 | `Orders`: finding, shipping, cancelling, revenue, best sellers |
| `services/customers.ts` | 115 | `Customers` |
| `services/accounts.ts` | 130 | `Accounts`: store credit and loyalty points |
| `services/shipping.ts` | 205 | `Shipping`: rates, shipments, dispatch, delivery, cancellation |
| `services/invoicing.ts` | 116 | `Invoicing` |
| `services/purchasing.ts` | 234 | `Purchasing`: suppliers, purchase orders, deliveries, reorders |
| `services/event-log.ts` | 90 | `EventLog`: record, subscribe, replay, read |
| `services/reports.ts` | 152 | `Reports` |
| `adapters/clock.ts` | 33 | `FixedClock`, `SequentialIds` |
| `adapters/memory.ts` | 267 | Each store in memory, `InMemoryPaymentGateway`, `InMemoryOutbox` |
| `adapters/recording.ts` | 63 | The recording stores |
| `adapters/text.ts` | 115 | The receipt, the invoice, the label, the packing slip, the statement, events as JSON lines |
| `adapters/csv.ts` | 96 | CSV out and in, the price list, the reports as CSV |
| `cart.ts` | 3 | Entry point: the cart |
| `catalogue.ts` | 11 | Entry point: the catalogue |
| `checkout.ts` | 4 | Entry point: the checkout |
| `clock.ts` | 5 | Entry point: the clock and the ids |
| `inventory.ts` | 12 | Entry point: the inventory |
| `orders.ts` | 11 | Entry point: the orders |
| `payments.ts` | 3 | Entry point: the payments |
| `promotions.ts` | 15 | Entry point: the promotions engine |
| `receipt.ts` | 3 | Entry point: the receipt |
| `customers.ts` | 22 | Entry point: customers and accounts |
| `shipping.ts` | 12 | Entry point: shipping |
| `invoices.ts` | 6 | Entry point: invoices |
| `purchasing.ts` | 12 | Entry point: purchasing |
| `events.ts` | 12 | Entry point: the event log |
| `reports.ts` | 21 | Entry point: reports |
| `shop.ts` | 136 | The composition root, `createShop` |

## The Go port

The Go port holds the same files, with `.go` for `.ts` and `_test.go` for `.test.ts`, and a hyphen in a name as an underscore (`services/promotion_engine.go`, `services/event_log.go`). The parity check (`seed_design` in `tests/task_packs.py`) compares the file names and the exported names with the language taken out.

- **Packages.** Each layer is a package: `shop/domain`, `shop/services`, `shop/adapters`. The root is package `shop` (module `shop`, as in rung D), whose files declare type aliases and variables for the names of the layers (`type Order = domain.Order`, `var NewOrders = services.NewOrders`), so that the Go feature tests of M and X run unchanged in the root package. Go forbids import cycles, which the layers already rule out.
- **Constructors.** A TypeScript class is a Go struct with a `New<Type>` function. The constructors of the small codebase keep the signatures of the Go rung D. A service that takes `deps` takes a `<Service>Deps` struct; an optional collaborator is a pointer or interface field that may be nil.
- **Errors.** `ShopError` is a struct with `Code` and `Message` that implements `error`, made by the same helpers (`NotFound`, `Invalid`, `Conflict`, `WrongState`, `Declined`, `Check`). A method that can fail returns `(T, error)` or `error`, as in rung D; the messages are the same, character for character.
- **Optional fields.** An optional field of a TypeScript record (`Order.customerId`, `Customer.address`, `Shipment.trackingCode`) is an empty string or a nil pointer in Go, as rung D does for `PaymentID`. Go has no `undefined` keys, so the tests that compare whole records compare the zero values.
- **Copies.** The stores copy records, slices and pointers as the TypeScript stores do (`CopyOrder` and so on in the domain).
- **Generics.** The `Table` of `adapters/memory.ts` and the `Recording` store of `adapters/recording.ts` are unexported generics; Go 1.27 has them.
- **Sorting.** `compareText` is Go's `<` on strings (both compare code units for ASCII), and every sort is stable with a tie-break, so both languages list in the same order.
- **Size.** Go is longer than TypeScript for the same design (error returns, struct literals). The TypeScript codebase sits near the bottom of the line range (4,099 of 4,000 to 6,000) for that reason: a Go port at 1.2 to 1.4 times the lines stays under 6,000. If the Go port goes over, shorten comments before you cut behaviour, because the seed suites must hold the same cases.
- **Tests.** Each `describe` is a `t.Run` group, and each `it` a `t.Run` inside it, with the same names; a TypeScript test file with no `describe` (`domain/cart.test.ts`, `adapters/clock.test.ts`) has `t.Run` cases at the top.

### What the port did

The Go codebase is 4,352 lines of production code in 49 files (1.06 times the TypeScript), and its seed suite has the same 33 files and the same 373 cases, in the same order. `tests/test_medium_codebase.py` checks both languages, and the parity of the seed design and the case names.

- **Imports.** The services and the adapters dot-import `shop/domain`, so that their code names the domain as the TypeScript does. The root files declare the aliases in grouped `type`, `const` and `var` blocks, and declare every name that rung D's root file of the same name declared, so that the Go feature tests of M pass unchanged in the root package; those of X fail there only on the names of X (`Returns`, `ReturnsDeps`, `NewReturns`, `ReturnLine`, `CreditNote`, `CreditLine`).
- **Names that only Go has.** `ShopError.Code`, `Message` and `Error()`; the functions of the report figures, named `<Figure>Of` (`SalesSummaryOf`), since Go has one name space for types and functions; and the fields of the `Shop` struct that `CreateShop` returns (the TypeScript `Shop` is an inferred type). `LANGUAGE_ONLY_NAMES` in `tests/task_packs.py` lists them; the parity check leaves them out.
- **Results with no named type.** `Inventory.ReservedFor`, `Accounts.CreditHolders` and `ImportResult.Rejected` give anonymous structs, as the TypeScript does, through unexported aliases (`holding`, `creditHolder`, `rejection`).
- **Stores.** Each store in memory is a small type over an unexported generic `table`; each recording store is an alias of the unexported generic `recording`.
- **Optional values.** An optional number is its zero value when absent (`ShippingRate.FreeFrom`, `MaxUnitsPerParcel`), except a tax rate, where 0 is a rate: `InvoicingDeps.TaxRate` and `ShopOptions.TaxRate` are `*int`. An optional argument is a nil pointer (`Customers.Register`, `Shipping.CreateShipment`) or a variadic (`Catalogue.Reprice`). `Purchasing.DraftReorder` gives nil when no SKU is short.
- **Dates.** `AddDays`, `EachDay`, `CheckDate` and `CheckPeriod` check their dates, as in TypeScript. `DaysBetween`, `MonthOf`, `StartOfMonth`, `EndOfMonth` and `Weekday` read the dates of records and return no error.
- **Events.** `ChangeSink.Record` returns the event and an error, so that `EventLog` implements it. A `Subscriber` returns nothing; `CreateShop` drops the errors of the accounts and shipping handlers, which cannot fail on the shop's own events, and a recording store drops the error of the sink.
- **Checks that Go makes for you.** A count, an amount or a rate is an `int`, so the checks for whole numbers have no Go form; the seed suite drops those assertions (and tests a negative tax rate and parcel limit), and keeps every case.
- **Tests.** Each seed test file stands alone, with its own helpers under a prefix of its own, because the verifier drops each unchanged seed test file in the agent pass (issue #83). No helper panics.
