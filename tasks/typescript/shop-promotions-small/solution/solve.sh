#!/usr/bin/env bash
# The gold solution: the promotions engine over the stub, connected to the
# checkout, and an order with no payment cancelled without a refund.
set -euo pipefail
for file in promotions.ts checkout.ts orders.ts; do
  cp "$(dirname "$0")/$file" "/app/$file"
done
