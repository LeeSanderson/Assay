#!/usr/bin/env bash
# The gold solution: the returns (domain/return.ts, services/returns.ts and the
# entry point returns.ts), which issue credit notes, and the changes to the
# promotions engine (the part of each discount on each line), the checkout
# (which keeps those parts on the order lines), the orders, the inventory
# (restock), the payments (part refunds), the ids (the prefix `credit`) and the
# composition root.
set -euo pipefail
here="$(dirname "$0")"
for file in returns.ts shop.ts \
  domain/return.ts domain/order.ts domain/promotion.ts domain/payment.ts domain/stock.ts \
  domain/ids.ts adapters/memory.ts services/returns.ts services/promotion-engine.ts \
  services/checkout.ts services/orders.ts services/inventory.ts; do
  cp "$here/$file" "/app/$file"
done
