# Instructions

Add partial returns and refunds to the shop in this repository.

The repository holds the shop: its catalogue, its inventory, its carts, its orders, its payments, its checkout and its promotions engine. The checkout prices a cart with the engine, reserves the stock, charges the payment and places the order. An order ships, and its stock then leaves the inventory.

A customer can send back some or all of the units of a shipped order, in one return or in several. Each return names the units that come back, and the condition of each line: resellable or damaged.

A return changes these parts of the shop:

- The order. The order keeps the units returned from each line, so that no unit is returned twice. When every unit of an order has come back, the order is returned. The revenue and the best sellers of the shop count only what the customers kept.
- The inventory. Resellable units go back into the stock. Damaged units do not.
- The prices. A return refunds what the customer paid for the units: their price, less their share of each discount of the order. A return reverses each discount in proportion to the units that come back, on the lines that the discount took from. Thus a bundle that is returned in part gets a new price, and a discount that took nothing from a line is not reversed when that line comes back.
- The payments. Each return issues a credit note, which records what the return refunds, and refunds that amount to the payment of the order.

A customer can return units up to 30 days after the order was placed. A return that fails changes nothing.

## Interface

Add `returns.go`, in `package shop`. It declares these types and functions:

```go
type ItemCondition string // "resellable" or "damaged"

type ReturnLine struct {
	SKU       string
	Quantity  int
	Condition ItemCondition
}

type CreditLine struct {
	SKU      string
	Quantity int
	Amount   int // what the credit note refunds for these units
}

type CreditNote struct {
	ID        string
	OrderID   string
	Lines     []CreditLine
	Discounts []Discount // the part of each discount of the order that the return reverses
	Amount    int        // the sum of the amounts of the lines
	IssuedOn  string
}

type ReturnsDeps struct {
	Orders    OrderRepository
	Inventory *Inventory
	Payments  PaymentGateway
	Clock     Clock
	IDs       IDSource
}

type Returns struct{ /* unexported fields */ }

func NewReturns(deps ReturnsDeps) *Returns
func (r *Returns) ReturnItems(orderID string, lines []ReturnLine) (CreditNote, error)
func (r *Returns) CreditNotes(orderID string) ([]CreditNote, error)
```

- `ReturnItems(orderID, lines)` returns the units of `lines` from the order with the id `orderID`, and gives the `CreditNote` of the return.
- `CreditNotes(orderID)` gives the credit notes of the order, in the order that they were issued; empty (nil or of length 0) when the order has had no return.
- An empty slice and a nil slice are the same: `Discounts` is empty when the return reverses nothing.
- On an error, the method returns an `error` whose `Error()` text is exactly one of the messages in "Errors" below, and a zero value.

These are the parts of the shop that the feature uses and changes. `Discount` is in `promotions.go`:

```go
// orders.go
type OrderStatus string // "paid", "shipped" or "cancelled", and now "returned"

func NewOrders(repository OrderRepository, inventory *Inventory, payments PaymentGateway) *Orders
func (o *Orders) Order(id string) (Order, error)
func (o *Orders) WithStatus(status OrderStatus) []Order
func (o *Orders) Ship(id string) error
func (o *Orders) Cancel(id string) error
func (o *Orders) Revenue() int
func (o *Orders) BestSellers(limit int) []SKUSales

// checkout.go
type CheckoutDeps struct {
	Catalogue  *Catalogue
	Inventory  *Inventory
	Orders     OrderRepository
	Payments   PaymentGateway
	Clock      Clock
	IDs        IDSource
	Promotions *PromotionEngine
}

// inventory.go
func (inv *Inventory) Level(sku string) StockLevel
func (inv *Inventory) Available(sku string) int
func (inv *Inventory) Movements(sku string) []StockMovement

// payments.go
func (g *InMemoryPaymentGateway) Refunds() []Refund // each refund: Refund{PaymentID, Amount}
```

The feature works in the shop as the repository builds it: a `Checkout` with a `PromotionEngine` in `deps.Promotions`, an `Orders` and a `Returns`, all over one `InMemoryOrderRepository`, one `Inventory`, one `InMemoryPaymentGateway`, one `FixedClock` and one `SequentialIDs`.

### Returns

- Only a shipped order can be returned. Its status stays `"shipped"` while it has units left to return. When every unit of every line has been returned, its status is `"returned"`, and the order can then be neither shipped, nor cancelled, nor returned again.
- A customer can return units up to and including 30 days after the date the order was placed (`PlacedOn`), on the date of `deps.Clock`. Dates are strings in the form `YYYY-MM-DD`.
- A return holds at least one line. Each line names a SKU of the order, once, and a quantity of at least 1, no more than the units of that line that have not been returned yet.
- A return keeps the lines of the order, their unit prices and quantities, and its `Subtotal`, `Discounts` and `Total`, as they were placed.
- A return that fails returns an error, and changes nothing: no stock, no refund, no credit note and no change to the order.

### Restock

- The resellable units of a return go back into the stock on hand of their SKU, and are available again. Each resellable line adds a stock movement `StockMovement{SKU: sku, Quantity: quantity, Reason: "returned"}`.
- Damaged units do not go back into stock, and add no stock movement.

### Refunds

All amounts are whole cents.

- The checkout takes each discount of an order from the remaining amounts of its lines, as the promotions engine (`promotions.go`) works it out when the order is placed. The part of a discount on a line is what that promotion took from the remaining amount of that line. For example, a `fixed` discount takes from the eligible lines in cart order, and a `bundle` takes its saving from the lines of its SKUs in cart order. A line can hold parts of several discounts, and a discount can have parts on several lines.
- A return reverses each part in proportion to the units of its line that come back. When `r` of the `q` units of a line have been returned in all, the returns of that line have reversed `floor(part * r / q)` of each part on it. A return reverses the difference between that amount after the return and that amount before it. Thus each reversal rounds down, and when every unit of a line has come back, every part on that line has been reversed in full.
- The `Amount` of a credit line is the unit price times the quantity returned, less what the return reverses of each part on that line.
- The `Discounts` of a credit note hold, for each discount of the order that the return reverses, the id of its promotion and the sum of what the return reverses of its parts on the lines of the return. They are in the order of the `Discounts` of the order. A discount that the return does not reverse is not in the list, which is empty when the return reverses nothing.
- The `Lines` of a credit note are the lines of the return, in the order of the return. The `Amount` of the credit note is the sum of the amounts of its lines.
- A credit note gets a new id from `deps.IDs` (with the prefix `"credit"`), the `OrderID` of the order, and the date of `deps.Clock` as `IssuedOn`.

### Payments

- When the `Amount` of a credit note is more than 0, the return refunds that amount to the payment of the order (`PaymentID`): `Refunds()` of the gateway then holds one more refund, `Refund{PaymentID, Amount}`.
- A credit note with an amount of 0 refunds nothing, and so does a return from an order with no payment.

### Orders

- `Revenue()` is the sum, over the orders that are not cancelled, of the total of the order less the amounts of its credit notes.
- `BestSellers(limit)` counts, for each SKU, the units sold and not returned over the orders that are not cancelled. A SKU with no such units is not in the list.
- `WithStatus("returned")` gives the returned orders.

### Errors

`<id>` stands for the id of the order, `<sku>` for the SKU of a line, `<n>` for a number and `<condition>` for the condition of a line.

- `unknown order <id>` (from `ReturnItems` or `CreditNotes`)
- `order <id> is <status>`: the order is not shipped (`paid`, `cancelled` or `returned`).
- `the return window of order <id> has closed`: the date is more than 30 days after the order was placed.
- `nothing to return`: the return holds no line.
- `SKU <sku> is not in order <id>`
- `SKU <sku> is in more than one line`
- `quantity must be at least 1`
- `unknown condition <condition>`: the condition is neither `"resellable"` nor `"damaged"`.
- `<sku> has <n> left to return`: the quantity is more than the `<n>` units of the line that have not been returned yet.

Add this feature to the repository. Keep the existing behavior, and the existing exported names and signatures, as they are. Tests that you cannot see will check your solution.
