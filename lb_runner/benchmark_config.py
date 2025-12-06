"""Runner-facing benchmark config shim.

Re-exports the existing benchmark_config definitions so runner imports are
stable while the module is migrated.
"""

from linux_benchmark_lib.benchmark_config import *  # noqa: F401,F403
