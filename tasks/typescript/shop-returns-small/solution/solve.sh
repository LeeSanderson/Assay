#!/usr/bin/env bash
# The gold solution: the returns, which issue credit notes, and the changes to
# the engine (the part of each discount on each line), the checkout (which
# keeps those parts on the order lines), the orders, the inventory (restock)
# and the payments (part refunds).
set -euo pipefail
for file in returns.ts promotions.ts checkout.ts orders.ts inventory.ts payments.ts; do
  cp "$(dirname "$0")/$file" "/app/$file"
done
