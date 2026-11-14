#!/usr/bin/env bash
# The gold solution: the returns, which issue credit notes, and the changes to
# the engine (the part of each discount on each line), the checkout (which
# keeps those parts on the order lines), the orders, the inventory (restock)
# and the payments (part refunds).
set -euo pipefail
for file in returns.go promotions.go checkout.go orders.go inventory.go payments.go; do
  cp "$(dirname "$0")/$file" "/app/$file"
done
