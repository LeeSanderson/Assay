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

`promotions.ts` holds the stub of the engine. It exports these types and the class `PromotionEngine`:

```ts
export type PromotionKind = 'percentage' | 'fixed' | 'buy-x-get-y' | 'bundle'

export interface Line {
  sku: string
  unitPrice: number
  quantity: number
}

export interface Promotion {
  id: string
  kind: PromotionKind
  skus?: string[] // percentage, fixed, buy-x-get-y: the eligible SKUs; bundle: the SKUs of its set
  percent?: number // percentage
  amount?: number // fixed
  buy?: number // buy-x-get-y: X
  get?: number // buy-x-get-y: Y
  price?: number // bundle: the price of one set
  priority?: number
  exclusive?: boolean
}

export interface Coupon {
  code: string
  promotion: Promotion
  expiresOn: string // the expiry date
  usageLimit: number
}

export interface Discount {
  promotionId: string
  amount: number
}

export interface Quote {
  subtotal: number
  discounts: Discount[]
  total: number
}
```

- `new PromotionEngine()` makes an engine with no promotions and no coupons.
- `addPromotion(promotion)` adds a promotion, which is considered for every cart.
- `addCoupon(coupon)` adds a coupon.
- `quote(lines, coupons, today)` prices the cart `lines` with the coupon codes `coupons` on the date `today`, and returns a `Quote`.
- `redeem(lines, coupons, today)` prices the cart as `quote` does, returns the same `Quote`, and uses each coupon in `coupons` once.
- In a `Promotion`, a missing `skus` is the empty list, a missing `priority` is 0, a missing `exclusive` is `false`, and any other missing number is 0.
- `discounts` is an empty array when no promotion applies.
- Each error is thrown as an `Error` whose message is exactly one of the messages in "Errors" below.

### Checkout

`checkout.ts` holds the checkout. These are the parts of the shop that the feature uses:

```ts
// checkout.ts
export interface CheckoutDeps {
  catalogue: Catalogue
  inventory: Inventory
  orders: OrderRepository
  payments: PaymentGateway
  clock: Clock
  ids: IdSource
  promotions?: PromotionEngine // the engine of the checkout
}

export interface CheckoutRequest {
  cart: Cart
  paymentToken: string
  coupons?: string[] // the coupon codes that the customer gives
}

export class Checkout {
  constructor(deps: CheckoutDeps)
  quote(cart: Cart, coupons: string[] = []): Quote
  placeOrder(request: CheckoutRequest): Order
}

// orders.ts
export interface Order {
  id: string
  lines: OrderLine[]
  subtotal: number
  discounts: Discount[]
  total: number
  status: OrderStatus // 'paid', 'shipped' or 'cancelled'
  paymentId: string
  placedOn: string
}
```

- When `deps.promotions` is set, `quote` and `placeOrder` price the cart with the engine. The engine gets the lines of the cart in cart order, each with its SKU, the unit price of the catalogue and its quantity; the coupon codes (a missing `coupons` is the empty list); and the date of `deps.clock`, as `today`.
- Without an engine, the checkout works as it does now: an order has no discounts, and the checkout ignores coupon codes.
- `quote` returns the `Quote` of the engine, and uses no coupon.
- `placeOrder` gives the order the `subtotal`, the `discounts` and the `total` of the engine, keeps the order lines at the prices of the catalogue, and charges the payment the `total`. It uses each coupon of the request once, as `redeem` does.
- When the total is 0, `placeOrder` charges no payment, and the `paymentId` of the order is the empty string `''`. The order is `'paid'`, as every placed order is.
- A checkout that fails changes nothing. When the engine throws, the stock is short, or the payment is declined, `placeOrder` throws that error with its message unchanged, uses no coupon, keeps no stock reserved, charges nothing and saves no order.
- `Orders.cancel(id)` (in `orders.ts`) refunds the payment of the order, which is the total after the discounts. It cancels an order with no payment without a refund. Cancelling an order does not give back its coupons.

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
