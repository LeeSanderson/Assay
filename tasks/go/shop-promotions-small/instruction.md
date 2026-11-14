# Instructions

Build the promotions engine of the shop in this repository, and connect it to the checkout.

The shop sells goods by SKU. A cart holds lines, and each line has a SKU, a unit price and a quantity. The promotions engine works out how much the shop takes off the price of a cart.

The engine holds promotions of four kinds:

- a percentage discount, which takes a percent off the price of some goods, or of the whole cart;
- a fixed discount, which takes an amount off;
- buy X get Y, which makes some units free when the customer buys enough of them;
- a bundle, which sells a set of goods together at one price.

The engine also holds coupons. A coupon has a code and carries a promotion, which applies only when the customer gives the code. A coupon has an expiry date and a usage limit: the number of times that it can be redeemed.

More than one promotion can apply to a cart. The rules for stacking, exclusivity and precedence decide which promotions apply, and in which order: each promotion has a priority, promotions stack, and an exclusive promotion does not share a cart with another promotion.

The engine can quote a price for a cart, which changes nothing, and redeem a cart at checkout, which uses the coupons that the customer gave.

The repository holds the shop: its catalogue, its inventory, its carts, its orders, its payments and its checkout. The checkout prices a cart at the prices of the catalogue, reserves the stock, charges the payment and places the order.

Connect the engine to the checkout. A checkout that has an engine prices each cart with it, takes the coupons that the customer gives, and charges the total after the discounts. A checkout that fails still changes nothing, and uses no coupon. An order that costs nothing is placed without a payment, and cancelling it refunds nothing.

## Interface

`promotions.go`, in `package shop`, holds the stub of the engine. It declares these types and functions:

```go
type PromotionKind string // "percentage", "fixed", "buy-x-get-y" or "bundle"

type Line struct {
	SKU       string
	UnitPrice int
	Quantity  int
}

type Promotion struct {
	ID        string
	Kind      PromotionKind
	SKUs      []string // percentage, fixed, buy-x-get-y: the eligible SKUs; bundle: the SKUs of its set
	Percent   int      // percentage
	Amount    int      // fixed
	Buy       int      // buy-x-get-y: X
	Get       int      // buy-x-get-y: Y
	Price     int      // bundle: the price of one set
	Priority  int
	Exclusive bool
}

type Coupon struct {
	Code       string
	Promotion  Promotion
	ExpiresOn  string // the expiry date
	UsageLimit int
}

type Discount struct {
	PromotionID string
	Amount      int
}

type Quote struct {
	Subtotal  int
	Discounts []Discount
	Total     int
}

type PromotionEngine struct{ /* unexported fields */ }
```

- `NewPromotionEngine()` makes an engine with no promotions and no coupons.
- `AddPromotion(promotion Promotion) error` adds a promotion, which is considered for every cart.
- `AddCoupon(coupon Coupon) error` adds a coupon.
- `Quote(lines []Line, coupons []string, today string) (Quote, error)` prices the cart `lines` with the coupon codes `coupons` on the date `today`, and returns a `Quote`.
- `Redeem(lines []Line, coupons []string, today string) (Quote, error)` prices the cart as `Quote` does, returns the same `Quote`, and uses each coupon in `coupons` once.
- In a `Promotion`, a nil `SKUs` is the empty list, and the zero values of the other fields are their defaults (priority 0, not exclusive).
- `Discounts` is empty (nil or of length 0) when no promotion applies.
- On an error, the method returns an `error` whose `Error()` text is exactly one of the messages in "Errors" below, and a zero `Quote`.

### Checkout

`checkout.go` holds the checkout. These are the parts of the shop that the feature uses:

```go
// checkout.go
type CheckoutDeps struct {
	Catalogue  *Catalogue
	Inventory  *Inventory
	Orders     OrderRepository
	Payments   PaymentGateway
	Clock      Clock
	IDs        IDSource
	Promotions *PromotionEngine // the engine of the checkout
}

type CheckoutRequest struct {
	Cart         *Cart
	PaymentToken string
	Coupons      []string // the coupon codes that the customer gives
}

func NewCheckout(deps CheckoutDeps) *Checkout
func (c *Checkout) Quote(cart *Cart, coupons []string) (Quote, error)
func (c *Checkout) PlaceOrder(request CheckoutRequest) (Order, error)

// orders.go
type Order struct {
	ID        string
	Lines     []OrderLine
	Subtotal  int
	Discounts []Discount
	Total     int
	Status    OrderStatus // "paid", "shipped" or "cancelled"
	PaymentID string
	PlacedOn  string
}
```

- When `deps.Promotions` is not nil, `Quote` and `PlaceOrder` price the cart with the engine. The engine gets the lines of the cart in cart order, each with its SKU, the unit price of the catalogue and its quantity; the coupon codes (nil is the empty list); and the date of `deps.Clock`, as `today`.
- Without an engine, the checkout works as it does now: an order has no discounts, and the checkout ignores coupon codes.
- `Quote` returns the `Quote` of the engine, and uses no coupon.
- `PlaceOrder` gives the order the `Subtotal`, the `Discounts` and the `Total` of the engine, keeps the order lines at the prices of the catalogue, and charges the payment the `Total`. It uses each coupon of the request once, as `Redeem` does.
- When the total is 0, `PlaceOrder` charges no payment, and the `PaymentID` of the order is the empty string `""`. The order is `"paid"`, as every placed order is.
- A checkout that fails changes nothing. When the engine returns an error, the stock is short, or the payment is declined, `PlaceOrder` returns that error with its text unchanged, uses no coupon, keeps no stock reserved, charges nothing and saves no order.
- `(*Orders).Cancel(id)` (in `orders.go`) refunds the payment of the order, which is the total after the discounts. It cancels an order with no payment without a refund. Cancelling an order does not give back its coupons.

### Pricing

- All amounts are whole cents. The subtotal of a cart is the sum, over its lines, of the unit price times the quantity.
- A `percentage`, `fixed` or `buy-x-get-y` promotion works on its eligible lines: the lines whose SKU is in its list of SKUs, or every line when the list is empty.
- Each line has a remaining amount, which starts at its unit price times its quantity. Each promotion takes its discount from the remaining amounts, so a promotion works on what the promotions before it left.
- The engine considers the promotions in order of precedence: the highest priority first, and promotions with the same priority in the order of their ids (string order).
- A `percentage` promotion takes the percent of the remaining amount of each eligible line, rounded down to a whole cent on each line.
- A `fixed` promotion takes its amount from the eligible lines in cart order: from each line, as much of its remaining amount as the promotion still needs. It takes no more than the eligible lines have left, so a total never goes below zero.
- A `buy-x-get-y` promotion makes Y units free for each full group of X + Y units on an eligible line, and counts the units of each line on its own. From each eligible line it takes the unit price times the free units, but no more than the remaining amount of that line.
- A `bundle` counts its sets: the smallest quantity among the lines of its SKUs, or no set when one of its SKUs has no line in the cart. The saving on one set is the sum of the unit prices of its SKUs minus the bundle price. The bundle takes the saving on all its sets from the lines of its SKUs in cart order, as a `fixed` promotion does. When the saving on one set is not more than zero, the bundle takes nothing.
- A promotion applies when it takes more than zero. The discounts of a quote are the promotions that applied, in the order that they applied, each with the id of the promotion and the amount that it took. A promotion that takes nothing is not in the discounts.
- Promotions stack: each promotion that applies takes its discount. The engine skips an exclusive promotion when a promotion before it has applied. When an exclusive promotion applies, the engine considers no more promotions. An exclusive promotion that takes nothing does not stop the promotions after it.
- The total is the subtotal minus the discounts.

### Coupons

- The promotion of a coupon is considered only when the cart is priced with the code of the coupon. It then takes its place among the other promotions, in the same order of precedence.
- Dates are strings in the form `YYYY-MM-DD`. A coupon can be used up to and including its expiry date.
- A quote uses no coupon. A redeem uses each coupon that it is given once, even when the promotion of the coupon takes nothing. When a coupon has been redeemed as many times as its usage limit, it cannot be quoted or redeemed again.
- A quote or a redeem that fails uses no coupon.

### Errors

`<id>`, `<kind>`, `<code>` and `<sku>` stand for the value.

- Adding a promotion, or adding a coupon (for its promotion):
  - `promotion <id> already exists`: the engine holds a promotion, or the promotion of a coupon, with this id.
  - `unknown promotion kind <kind>`
  - `percent must be between 1 and 100` (a `percentage` promotion)
  - `amount must be positive` (a `fixed` promotion)
  - `buy and get must be at least 1` (a `buy-x-get-y` promotion: X or Y is below 1)
  - `a bundle needs at least two SKUs`
  - `bundle price must not be negative`
- Adding a coupon:
  - `coupon <code> already exists`
  - `usage limit must be at least 1`
- Quoting or redeeming a cart:
  - `quantity must be at least 1`: a line has a quantity below 1.
  - `SKU <sku> is in more than one line`
  - `unknown coupon <code>`
  - `coupon <code> given more than once`: the coupon codes hold the same code twice.
  - `coupon <code> has expired`: the date is after the expiry date of the coupon.
  - `coupon <code> has reached its usage limit`
- An add that fails adds nothing.

Add this feature to the repository. Keep the existing behavior, and the existing exported names and signatures, as they are. Tests that you cannot see will check your solution.
