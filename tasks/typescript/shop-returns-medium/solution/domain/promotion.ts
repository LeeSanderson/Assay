// Promotions: the rules that take money off a cart. A promotion is a
// percentage or a fixed amount off, buy X get Y free, or a bundle price for a
// set of SKUs. The pricing works line by line on what earlier promotions left
// of each line, so that the discounts never take a line below zero. What each
// promotion took from a line is its part of the discount on that line.

import { invalid } from './errors.ts'
import { compareText } from './ids.ts'
import { formatCents, percentOf, sum, takeInOrder, times } from './money.ts'
import type { Cents } from './money.ts'

export type PromotionKind = 'percentage' | 'fixed' | 'buy-x-get-y' | 'bundle'

export interface Line {
  sku: string
  unitPrice: Cents
  quantity: number
}

export interface Promotion {
  id: string
  kind: PromotionKind
  skus?: string[] // the SKUs that it applies to; every SKU when absent or empty
  percent?: number // percentage
  amount?: Cents // fixed
  buy?: number // buy-x-get-y
  get?: number // buy-x-get-y
  price?: Cents // bundle: the price of one set of its SKUs
  priority?: number // higher first; 0 when absent
  exclusive?: boolean // applies only alone
}

export interface Coupon {
  code: string
  promotion: Promotion
  expiresOn: string
  usageLimit: number
}

export interface Discount {
  promotionId: string
  amount: Cents
}

export interface Quote {
  subtotal: Cents
  discounts: Discount[]
  total: Cents
}

const KINDS: readonly string[] = ['percentage', 'fixed', 'buy-x-get-y', 'bundle']

export function validatePromotion(promotion: Promotion): void {
  if (!KINDS.includes(promotion.kind)) {
    throw invalid(`unknown promotion kind ${promotion.kind}`)
  }
  const percent = promotion.percent ?? 0
  const amount = promotion.amount ?? 0
  const buy = promotion.buy ?? 0
  const get = promotion.get ?? 0
  const price = promotion.price ?? 0
  switch (promotion.kind) {
    case 'percentage':
      if (percent < 1 || percent > 100) throw invalid('percent must be between 1 and 100')
      break
    case 'fixed':
      if (amount <= 0) throw invalid('amount must be positive')
      break
    case 'buy-x-get-y':
      if (buy < 1 || get < 1) throw invalid('buy and get must be at least 1')
      break
    case 'bundle':
      if ((promotion.skus ?? []).length < 2) throw invalid('a bundle needs at least two SKUs')
      if (price < 0) throw invalid('bundle price must not be negative')
      break
  }
}

// The order in which promotions are considered: the highest priority first,
// then by id.
export function precedence(a: Promotion, b: Promotion): number {
  const byPriority = (b.priority ?? 0) - (a.priority ?? 0)
  if (byPriority !== 0) return byPriority
  return compareText(a.id, b.id)
}

// Checks the lines of a cart: a quantity of at least 1, and each SKU once.
export function checkLines(lines: readonly Line[]): void {
  const skus = new Set<string>()
  for (const line of lines) {
    if (line.quantity < 1) throw invalid('quantity must be at least 1')
    if (skus.has(line.sku)) throw invalid(`SKU ${line.sku} is in more than one line`)
    skus.add(line.sku)
  }
}

// Applies one promotion to the remaining amounts of the lines, and gives what
// it took off in all. It changes `remaining`.
export function applyPromotion(promotion: Promotion, lines: readonly Line[], remaining: Cents[]) {
  const skus = promotion.skus ?? []
  const eligible = lines
    .map((line, i) => ({ line, i }))
    .filter(({ line }) => skus.length === 0 || skus.includes(line.sku))
  switch (promotion.kind) {
    case 'percentage': {
      let total = 0
      for (const { i } of eligible) {
        const discount = percentOf(remaining[i], promotion.percent ?? 0)
        remaining[i] -= discount
        total += discount
      }
      return total
    }
    case 'fixed':
      return takeInOrder(
        remaining,
        eligible.map(({ i }) => i),
        promotion.amount ?? 0
      )
    case 'buy-x-get-y': {
      const group = (promotion.buy ?? 0) + (promotion.get ?? 0)
      let total = 0
      for (const { line, i } of eligible) {
        const free = Math.floor(line.quantity / group) * (promotion.get ?? 0)
        const discount = Math.min(times(line.unitPrice, free), remaining[i])
        remaining[i] -= discount
        total += discount
      }
      return total
    }
    case 'bundle': {
      const members = skus.map((sku) => lines.findIndex((line) => line.sku === sku))
      if (members.includes(-1)) return 0
      const sets = Math.min(...members.map((i) => lines[i].quantity))
      const full = sum(members.map((i) => lines[i].unitPrice))
      const saving = full - (promotion.price ?? 0)
      if (sets === 0 || saving <= 0) return 0
      const inCartOrder = [...members].sort((a, b) => a - b)
      return takeInOrder(remaining, inCartOrder, times(saving, sets))
    }
    default:
      return 0
  }
}

// Prices the lines with the promotions, in order of precedence. Each
// promotion works on what the earlier ones left. An exclusive promotion
// applies only when no earlier promotion took anything off, and then stops
// the rest. A promotion that takes nothing off is left out.
export function priceLines(lines: readonly Line[], promotions: readonly Promotion[]): Quote {
  const steps = explainPricing(lines, promotions)
  const subtotal = sum(lines.map((line) => times(line.unitPrice, line.quantity)))
  const discounts: Discount[] = steps
    .filter((step) => step.outcome === 'applied')
    .map((step) => ({ promotionId: step.promotionId, amount: step.amount }))
  const total = subtotal - sum(discounts.map((discount) => discount.amount))
  return { subtotal, discounts, total }
}

// What happened to one promotion when the lines were priced.
export type Outcome =
  | 'applied' // it took `amount` off
  | 'nothing to take' // it applies to none of the lines, or what is left of them
  | 'not alone' // it is exclusive, and an earlier promotion applied
  | 'after exclusive' // an exclusive promotion applied before it

export interface PricingStep {
  promotionId: string
  outcome: Outcome
  amount: Cents
}

// Each promotion, in order of precedence, with what it did to the lines: the
// reasons behind a quote.
export function explainPricing(
  lines: readonly Line[],
  promotions: readonly Promotion[]
): PricingStep[] {
  return pricing(lines, promotions).steps
}

// The part of each discount on each line, as `priceLines` prices them: what
// each promotion took from the remaining amount of the line. One list for
// each line, in the order that the promotions applied; no part of 0.
export function discountsByLine(
  lines: readonly Line[],
  promotions: readonly Promotion[]
): Discount[][] {
  return pricing(lines, promotions).parts
}

function pricing(
  lines: readonly Line[],
  promotions: readonly Promotion[]
): { steps: PricingStep[]; parts: Discount[][] } {
  checkLines(lines)
  const remaining = lines.map((line) => times(line.unitPrice, line.quantity))
  const parts: Discount[][] = lines.map(() => [])
  const steps: PricingStep[] = []
  let applied = 0
  let stopped = false
  for (const promotion of [...promotions].sort(precedence)) {
    const step = (outcome: Outcome, amount = 0) =>
      steps.push({ promotionId: promotion.id, outcome, amount })
    if (stopped) {
      step('after exclusive')
    } else if (promotion.exclusive && applied > 0) {
      step('not alone')
    } else {
      const before = [...remaining]
      const amount = applyPromotion(promotion, lines, remaining)
      remaining.forEach((left, i) => {
        if (left < before[i]) parts[i].push({ promotionId: promotion.id, amount: before[i] - left })
      })
      if (amount === 0) {
        step('nothing to take')
      } else {
        step('applied', amount)
        applied += 1
        stopped = promotion.exclusive === true
      }
    }
  }
  return { steps, parts }
}

// A promotion in words, as the shop shows it to customers.
export function describePromotion(promotion: Promotion): string {
  const skus = promotion.skus ?? []
  const on = skus.length === 0 ? 'everything' : skus.join(', ')
  let text: string
  switch (promotion.kind) {
    case 'percentage':
      text = `${promotion.percent}% off ${on}`
      break
    case 'fixed':
      text = `${formatCents(promotion.amount ?? 0)} off ${on}`
      break
    case 'buy-x-get-y':
      text = `buy ${promotion.buy} get ${promotion.get} free on ${on}`
      break
    case 'bundle':
      text = `${skus.join(' + ')} for ${formatCents(promotion.price ?? 0)}`
      break
    default:
      text = promotion.kind
  }
  return promotion.exclusive ? `${text} (not with other offers)` : text
}
