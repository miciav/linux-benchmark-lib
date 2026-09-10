#!/usr/bin/env bash
set -euo pipefail

# Static dead-code scan with Vulture.
#
# Scope: every first-party package. Tests are deliberately NOT scanned - they
# assign mock/fixture variables purely for their side effects (monkeypatch
# targets, MagicMock handles), which vulture reports as "unused variable" at
# 100% confidence. A scan that is mostly false positives gets ignored, so it is
# better to keep this focused on shipped code.
#
# Run with --min-confidence 60 locally for a noisier sweep when hunting for
# dead code after a refactor.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

uv run --frozen vulture \
  lb_runner \
  lb_controller \
  lb_app \
  lb_ui \
  lb_gui \
  lb_analytics \
  lb_common \
  lb_plugins \
  lb_provisioner \
  scripts \
  --min-confidence 80 \
  "$@"
