from lb_plugins.plugins.peva_faas.plugin import DfaasPlugin


def test_peva_faas_plugin_name() -> None:
    assert DfaasPlugin.NAME == "peva_faas"


def test_peva_faas_setup_playbook_path() -> None:
    assert DfaasPlugin.SETUP_PLAYBOOK.name == "setup_plugin.yml"


def test_peva_faas_plugin_declares_uv_extra() -> None:
    assert DfaasPlugin.REQUIRED_UV_EXTRAS == ["peva_faas"]
