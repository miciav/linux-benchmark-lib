## Configuration

All knobs are defined in `BenchmarkConfig`:

```python
from pathlib import Path
from lb_runner.benchmark_config import BenchmarkConfig
from lb_runner.plugins.stress_ng.plugin import StressNGConfig

config = BenchmarkConfig(
    repetitions=5,
    test_duration_seconds=120,
    metrics_interval_seconds=0.5,
    plugin_settings={
        "stress_ng": StressNGConfig(
            cpu_workers=4,
            vm_workers=2,
            vm_bytes="2G",
        )
    },
)

config.save(Path("my_config.json"))
config = BenchmarkConfig.load(Path("my_config.json"))
```