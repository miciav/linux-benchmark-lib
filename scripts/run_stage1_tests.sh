#!/usr/bin/env bash
set -euo pipefail

uv run pytest \
  tests/unit/common/test_dd_plugin.py \
  tests/unit/common/test_stress_ng_plugin.py \
  tests/unit/common/test_sysbench_plugin.py \
  tests/unit/common/test_unixbench_plugin.py \
  tests/unit/common/test_geekbench_plugin.py \
  tests/unit/common/test_yabs_plugin.py \
  tests/unit/common/test_fio_plugin.py \
  tests/unit/common/test_fio_plugin_export.py \
  tests/unit/common/test_plugin_registry.py \
  tests/unit/lb_runner/test_plugin_registry_user_plugins.py \
  tests/unit/lb_runner/test_plugin_parsers.py \
  tests/unit/lb_runner/plugins \
  tests/unit/lb_ui/test_adapters_dashboard.py \
  tests/unit/lb_ui/test_picker_crash.py
