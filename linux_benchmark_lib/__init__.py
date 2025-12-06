"""Compatibility root for legacy imports.

Imports have moved to lb_runner, lb_controller, and lb_ui. This package
remains to avoid breaking existing module paths but does not eagerly
import subpackages to prevent circular dependencies.
"""
