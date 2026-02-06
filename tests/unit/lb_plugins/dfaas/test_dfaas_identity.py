import types

import lb_plugins.plugins.dfaas.plugin as dfaas_plugin_mod
from lb_plugins.plugins.dfaas.config import DfaasConfig
from lb_plugins.plugins.dfaas.plugin import DfaasPlugin


def test_dfaas_plugin_name() -> None:
    assert DfaasPlugin.NAME == "dfaas"


def test_dfaas_setup_playbook_path() -> None:
    assert DfaasPlugin.SETUP_PLAYBOOK.name == "setup_plugin.yml"


def test_dfaas_plugin_declares_uv_extra() -> None:
    assert DfaasPlugin.REQUIRED_UV_EXTRAS == ["dfaas"]


def test_dfaas_generator_is_lazy_loaded() -> None:
    assert DfaasPlugin.GENERATOR_CLS is None


def test_dfaas_create_generator_uses_dynamic_import(
    monkeypatch,
) -> None:
    class _FakeGenerator:
        def __init__(self, config):
            self.config = config

    def _fake_import(module_name: str) -> types.SimpleNamespace:
        assert module_name == "lb_plugins.plugins.dfaas.generator"
        return types.SimpleNamespace(DfaasGenerator=_FakeGenerator)

    monkeypatch.setattr(dfaas_plugin_mod, "import_module", _fake_import)

    generator = DfaasPlugin().create_generator(DfaasConfig())

    assert isinstance(generator, _FakeGenerator)
