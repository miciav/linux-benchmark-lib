import types

import pytest

from services.plugin_service import regenerate_plugin_assets


def test_regenerate_plugin_assets_invokes_generator(monkeypatch: pytest.MonkeyPatch):
    called = {}

    fake_module = types.SimpleNamespace()

    def fake_generate():
        called["ok"] = True

    fake_module.generate = fake_generate
    monkeypatch.setitem(
        globals(),
        "tools.gen_plugin_assets",
        fake_module,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "tools.gen_plugin_assets",
        fake_module,
    )

    regenerate_plugin_assets()
    assert called.get("ok") is True
