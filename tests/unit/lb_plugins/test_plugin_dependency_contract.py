import pytest

from lb_plugins.api import _build_plugin_assets, merge_plugin_assets
from lb_plugins.interface import SimpleWorkloadPlugin
from lb_plugins.plugin_assets import PluginAssetConfig

pytestmark = [pytest.mark.unit_plugins]


def test_simple_plugin_exposes_required_uv_extras() -> None:
    class P(SimpleWorkloadPlugin):
        NAME = "p"
        REQUIRED_UV_EXTRAS = ["peva_faas"]

    assert P().get_required_uv_extras() == ["peva_faas"]


def test_build_plugin_assets_includes_required_uv_extras() -> None:
    class P(SimpleWorkloadPlugin):
        NAME = "p"
        REQUIRED_UV_EXTRAS = ["peva_faas"]

    assets = _build_plugin_assets(P())
    assert assets.required_uv_extras == ["peva_faas"]


def test_merge_plugin_assets_preserves_user_overrides_and_fills_uv_extras() -> None:
    class P(SimpleWorkloadPlugin):
        NAME = "p"
        REQUIRED_UV_EXTRAS = ["dfaas"]

    class FakeRegistry:
        def available(self, load_entrypoints: bool = True):  # noqa: ARG002
            return {"p": P()}

    class FakeConfig:
        def __init__(self) -> None:
            self.plugin_assets = {
                "p": PluginAssetConfig(
                    setup_playbook=None,
                    teardown_playbook=None,
                    required_uv_extras=[],
                )
            }

    cfg = FakeConfig()
    merge_plugin_assets(cfg, FakeRegistry())  # type: ignore[arg-type]

    assert cfg.plugin_assets["p"].setup_playbook is None
    assert cfg.plugin_assets["p"].teardown_playbook is None
    assert cfg.plugin_assets["p"].required_uv_extras == ["dfaas"]
