#!/bin/bash
# Probe (wayfinder ticket 55): run the tool from the image mount, then the gold solution.
set -euo pipefail
{
  echo "--- ls /opt/assay-tools/bin"; ls -l /usr/local/bin/assay-probe-tool
  echo "--- run"; /usr/local/bin/assay-probe-tool from-trial
  echo "--- write test (expect read-only)"; touch /opt/assay-tools/x 2>&1 || echo "write refused: ok"
  echo "--- mount"; grep assay-tools /proc/mounts || true
} | tee /logs/agent/mount-probe.txt
cp "$(dirname "$0")/example.go" /app/split_second_stopwatch.go
