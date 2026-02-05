from __future__ import annotations

import pytest

from lb_plugins.plugins.peva_faas.config import DfaasOverloadConfig
from lb_plugins.plugins.peva_faas.services.cooldown import MetricsSnapshot
from lb_plugins.plugins.peva_faas.services.result_builder import DfaasResultBuilder

pytestmark = [pytest.mark.unit_plugins]


def test_build_result_row_flags_overload() -> None:
    builder = DfaasResultBuilder(DfaasOverloadConfig())
    all_functions = ["figlet"]
    config_pairs = [("figlet", 10)]
    summary_metrics = {
        "figlet": {"success_rate": 0.5, "avg_latency": 12.0, "request_count": 5}
    }
    replicas = {"figlet": 1}
    metrics = {
        "cpu_usage_node": 10.0,
        "ram_usage_node": 256.0,
        "ram_usage_node_pct": 50.0,
        "power_usage_node": 5.0,
        "functions": {"figlet": {"cpu": 1.0, "ram": 2.0, "power": 3.0}},
    }
    idle = MetricsSnapshot(cpu=1.0, ram=2.0, ram_pct=3.0, power=4.0)

    row, overloaded = builder.build_result_row(
        all_functions,
        config_pairs,
        summary_metrics,
        replicas,
        metrics,
        idle,
        rest_seconds=5,
    )

    assert overloaded is True
    assert row["overloaded_function_figlet"] == 1
    assert row["overloaded_node"] == 1
    assert row["success_rate_function_figlet"] == "0.500"


def test_build_skipped_row_includes_only_config_functions() -> None:
    builder = DfaasResultBuilder(DfaasOverloadConfig())
    row = builder.build_skipped_row(["figlet", "other"], [("figlet", 0)])

    assert row["function_figlet"] == "figlet"
    assert row["rate_function_figlet"] == 0
    assert row["function_other"] == ""
    assert row["rate_function_other"] == ""


def test_format_float_handles_nan() -> None:
    builder = DfaasResultBuilder(DfaasOverloadConfig())
    row, _ = builder.build_result_row(
        ["figlet"],
        [("figlet", 1)],
        {"figlet": {"success_rate": 1.0, "avg_latency": 0.0, "request_count": 0}},
        {"figlet": 1},
        {
            "cpu_usage_node": float("nan"),
            "ram_usage_node": float("nan"),
            "ram_usage_node_pct": float("nan"),
            "power_usage_node": float("nan"),
            "functions": {
                "figlet": {
                    "cpu": float("nan"),
                    "ram": float("nan"),
                    "power": float("nan"),
                }
            },
        },
        MetricsSnapshot(
            cpu=float("nan"), ram=float("nan"), ram_pct=float("nan"), power=float("nan")
        ),
        rest_seconds=0,
    )

    assert row["cpu_usage_node"] == "nan"
    assert row["cpu_usage_idle_node"] == "nan"
