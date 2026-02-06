import pytest

from lb_plugins.interface import SimpleWorkloadPlugin

pytestmark = [pytest.mark.unit_plugins]


def test_simple_plugin_exposes_required_uv_extras() -> None:
    class P(SimpleWorkloadPlugin):
        NAME = "p"
        REQUIRED_UV_EXTRAS = ["peva_faas"]

    assert P().get_required_uv_extras() == ["peva_faas"]
