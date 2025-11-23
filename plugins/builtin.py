"""Built-in workload plugins shipped with the library."""

from typing import List

from benchmark_config import DDConfig, FIOConfig, IPerf3Config, StressNGConfig
from workload_generators import DDGenerator, FIOGenerator, IPerf3Generator, StressNGGenerator

from .registry import WorkloadPlugin


STRESS_NG_PLUGIN = WorkloadPlugin(
    name="stress_ng",
    description="CPU/IO/memory stress via stress-ng",
    config_cls=StressNGConfig,
    factory=StressNGGenerator,
)

IPERF3_PLUGIN = WorkloadPlugin(
    name="iperf3",
    description="Network throughput via iperf3 client",
    config_cls=IPerf3Config,
    factory=IPerf3Generator,
)

DD_PLUGIN = WorkloadPlugin(
    name="dd",
    description="Sequential disk I/O via dd",
    config_cls=DDConfig,
    factory=DDGenerator,
)

FIO_PLUGIN = WorkloadPlugin(
    name="fio",
    description="Flexible disk I/O via fio",
    config_cls=FIOConfig,
    factory=FIOGenerator,
)


def builtin_plugins() -> List[WorkloadPlugin]:
    """Return built-in workload plugins."""
    return [
        STRESS_NG_PLUGIN,
        IPERF3_PLUGIN,
        DD_PLUGIN,
        FIO_PLUGIN,
    ]
