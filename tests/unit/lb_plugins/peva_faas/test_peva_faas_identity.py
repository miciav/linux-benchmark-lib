from lb_plugins.plugins.peva_faas.plugin import DfaasPlugin


def test_peva_faas_plugin_name() -> None:
    assert DfaasPlugin.NAME == "peva_faas"
