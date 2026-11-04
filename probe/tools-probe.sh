#!/bin/bash
# Probe (wayfinder ticket 57): run by ToolsProbeOracle.run() through Harbor's exec
# (non-login bash -c), after setup() linked the tools into /usr/local/bin.
set -uo pipefail
{
  echo "--- whoami: $(whoami)"; echo "--- PATH: $PATH"
  echo "--- shell options: $-"; shopt -q login_shell && echo login || echo "not a login shell"
  echo "--- command -v semgrep: $(command -v semgrep)"; echo "--- resolves to: $(readlink -f "$(command -v semgrep)")"
  echo "--- semgrep --version"; semgrep --version
  echo "--- links in /usr/local/bin"; find /usr/local/bin -type l -printf '%p -> %l\n'
  echo "--- git status in /app (expect empty)"; git -C /app status --porcelain --ignored
} 2>&1 | tee /logs/agent/tools-probe.txt
