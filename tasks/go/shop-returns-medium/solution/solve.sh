#!/usr/bin/env bash
# The gold solution: the returns (domain/return.go, services/returns.go and the
# entry point returns.go), which issue credit notes, and the changes to the
# promotions engine (the part of each discount on each line), the checkout
# (which keeps those parts on the order lines), the orders, the inventory
# (restock), the payments (part refunds), the ids (the prefix `credit`) and the
# composition root.
set -euo pipefail
here="$(dirname "$0")"
for file in returns.go shop.go \
  domain/return.go domain/order.go domain/promotion.go domain/payment.go domain/stock.go \
  domain/ids.go adapters/memory.go services/returns.go services/promotion_engine.go \
  services/checkout.go services/orders.go services/inventory.go; do
  cp "$here/$file" "/app/$file"
done
