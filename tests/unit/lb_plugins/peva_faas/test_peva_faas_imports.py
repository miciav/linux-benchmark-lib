from __future__ import annotations

import importlib

import pytest

pytestmark = [pytest.mark.unit_plugins]


def test_peva_faas_modules_import_without_cycles() -> None:
    importlib.import_module("lb_plugins.plugins.peva_faas.generator")
    importlib.import_module("lb_plugins.plugins.peva_faas.plugin")
