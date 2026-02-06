from lb_plugins.plugins.dfaas.plugin import DfaasPlugin


def test_dfaas_plugin_name() -> None:
    assert DfaasPlugin.NAME == "dfaas"


def test_dfaas_setup_playbook_path() -> None:
    assert DfaasPlugin.SETUP_PLAYBOOK.name == "setup_plugin.yml"
