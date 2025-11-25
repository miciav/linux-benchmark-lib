"""Plugin utilities for workload generators."""

from .registry import PluginRegistry
from .interface import WorkloadPlugin

__all__ = ["PluginRegistry", "WorkloadPlugin"]