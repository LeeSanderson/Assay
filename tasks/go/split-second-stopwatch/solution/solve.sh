#!/bin/bash
# Gold solution: copy the Exercism `.meta/example.go` over the stub.
set -euo pipefail
cp "$(dirname "$0")/example.go" /app/split_second_stopwatch.go
