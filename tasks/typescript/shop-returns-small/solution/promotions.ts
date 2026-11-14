export type PromotionKind = 'percentage' | 'fixed' | 'buy-x-get-y' | 'bundle'

export interface Line {
  sku: string
  unitPrice: number
  quantity: number
}

export interface Promotion {
  id: string
  kind: PromotionKind
  skus?: string[]
  percent?: number
  amount?: number
  buy?: number
  get?: number
  price?: number
  priority?: number
  exclusive?: boolean
}

export interface Coupon {
  code: string
  promotion: Promotion
  expiresOn: string
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

const KINDS: readonly string[] = ['percentage', 'fixed', 'buy-x-get-y', 'bundle']

function validate(promotion: Promotion): void {
  if (!KINDS.includes(promotion.kind)) {
    throw new Error(`unknown promotion kind ${promotion.kind}`)
  }
  const percent = promotion.percent ?? 0
  const amount = promotion.amount ?? 0
  const buy = promotion.buy ?? 0
  const get = promotion.get ?? 0
  const price = promotion.price ?? 0
  switch (promotion.kind) {
    case 'percentage':
      if (percent < 1 || percent > 100) throw new Error('percent must be between 1 and 100')
      break
    case 'fixed':
      if (amount <= 0) throw new Error('amount must be positive')
      break
    case 'buy-x-get-y':
      if (buy < 1 || get < 1) throw new Error('buy and get must be at least 1')
      break
    case 'bundle':
      if ((promotion.skus ?? []).length < 2) throw new Error('a bundle needs at least two SKUs')
      if (price < 0) throw new Error('bundle price must not be negative')
      break
  }
}

// The order in which promotions are considered: the highest priority first,
// then by id.
function precedence(a: Promotion, b: Promotion): number {
  const byPriority = (b.priority ?? 0) - (a.priority ?? 0)
  if (byPriority !== 0) return byPriority
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

// Takes up to `amount` from the remaining amounts of the given lines, in cart
// order, and returns what it took.
function takeInOrder(remaining: number[], indexes: number[], amount: number): number {
  let left = amount
  for (const i of indexes) {
    const take = Math.min(left, remaining[i])
    remaining[i] -= take
    left -= take
  }
  return amount - left
}

function apply(promotion: Promotion, lines: Line[], remaining: number[]): number {
  const skus = promotion.skus ?? []
  const eligible = lines
    .map((line, i) => ({ line, i }))
    .filter(({ line }) => skus.length === 0 || skus.includes(line.sku))
  switch (promotion.kind) {
    case 'percentage': {
      let total = 0
      for (const { i } of eligible) {
        const discount = Math.floor((remaining[i] * (promotion.percent ?? 0)) / 100)
        remaining[i] -= discount
        total += discount
      }
      return total
    }
    case 'fixed':
      return takeInOrder(remaining, eligible.map(({ i }) => i), promotion.amount ?? 0)
    case 'buy-x-get-y': {
      const group = (promotion.buy ?? 0) + (promotion.get ?? 0)
      let total = 0
      for (const { line, i } of eligible) {
        const free = Math.floor(line.quantity / group) * (promotion.get ?? 0)
        const discount = Math.min(free * line.unitPrice, remaining[i])
        remaining[i] -= discount
        total += discount
      }
      return total
    }
    case 'bundle': {
      const members = skus.map((sku) => lines.findIndex((line) => line.sku === sku))
      if (members.includes(-1)) return 0
      const sets = Math.min(...members.map((i) => lines[i].quantity))
      const full = members.reduce((sum, i) => sum + lines[i].unitPrice, 0)
      const saving = full - (promotion.price ?? 0)
      if (sets === 0 || saving <= 0) return 0
      const inCartOrder = [...members].sort((a, b) => a - b)
      return takeInOrder(remaining, inCartOrder, sets * saving)
    }
  }
}

export class PromotionEngine {
  private readonly promotions: Promotion[] = []
  private readonly coupons = new Map<string, Coupon>()
  private readonly uses = new Map<string, number>()

  public addPromotion(promotion: Promotion): void {
    this.checkNewPromotion(promotion)
    this.promotions.push(promotion)
  }

  public addCoupon(coupon: Coupon): void {
    if (this.coupons.has(coupon.code)) {
      throw new Error(`coupon ${coupon.code} already exists`)
    }
    if (coupon.usageLimit < 1) throw new Error('usage limit must be at least 1')
    this.checkNewPromotion(coupon.promotion)
    this.coupons.set(coupon.code, coupon)
    this.uses.set(coupon.code, 0)
  }

  public quote(lines: Line[], coupons: string[], today: string): Quote {
    return this.price(lines, coupons, today).quote
  }

  public redeem(lines: Line[], coupons: string[], today: string): Quote {
    const quote = this.price(lines, coupons, today).quote
    for (const code of coupons) {
      this.uses.set(code, (this.uses.get(code) ?? 0) + 1)
    }
    return quote
  }

  // The part of each discount on each line: what each promotion took from the
  // remaining amount of the line, as `quote` prices the cart. One list for
  // each line, in the order that the promotions applied; no part of 0.
  public discountsByLine(lines: Line[], coupons: string[], today: string): Discount[][] {
    return this.price(lines, coupons, today).parts
  }

  private checkNewPromotion(promotion: Promotion): void {
    const ids = [...this.promotions, ...[...this.coupons.values()].map((c) => c.promotion)]
    if (ids.some((p) => p.id === promotion.id)) {
      throw new Error(`promotion ${promotion.id} already exists`)
    }
    validate(promotion)
  }

  private price(
    lines: Line[],
    codes: string[],
    today: string
  ): { quote: Quote; parts: Discount[][] } {
    const skus = new Set<string>()
    for (const line of lines) {
      if (line.quantity < 1) throw new Error('quantity must be at least 1')
      if (skus.has(line.sku)) throw new Error(`SKU ${line.sku} is in more than one line`)
      skus.add(line.sku)
    }
    const considered = [...this.promotions]
    const given = new Set<string>()
    for (const code of codes) {
      if (given.has(code)) throw new Error(`coupon ${code} given more than once`)
      given.add(code)
      const coupon = this.coupons.get(code)
      if (coupon === undefined) throw new Error(`unknown coupon ${code}`)
      if (today > coupon.expiresOn) throw new Error(`coupon ${code} has expired`)
      if ((this.uses.get(code) ?? 0) >= coupon.usageLimit) {
        throw new Error(`coupon ${code} has reached its usage limit`)
      }
      considered.push(coupon.promotion)
    }
    considered.sort(precedence)

    const remaining = lines.map((line) => line.unitPrice * line.quantity)
    const subtotal = remaining.reduce((sum, amount) => sum + amount, 0)
    const discounts: Discount[] = []
    const parts: Discount[][] = lines.map(() => [])
    for (const promotion of considered) {
      if (promotion.exclusive && discounts.length > 0) continue
      const before = [...remaining]
      const amount = apply(promotion, lines, remaining)
      if (amount === 0) continue
      discounts.push({ promotionId: promotion.id, amount })
      remaining.forEach((left, i) => {
        if (left < before[i]) parts[i].push({ promotionId: promotion.id, amount: before[i] - left })
      })
      if (promotion.exclusive) break
    }
    const total = subtotal - discounts.reduce((sum, d) => sum + d.amount, 0)
    return { quote: { subtotal, discounts, total }, parts }
  }
}
