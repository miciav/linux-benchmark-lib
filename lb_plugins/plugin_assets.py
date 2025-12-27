"""Plugin asset metadata models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PluginAssetConfig(BaseModel):
    """Ansible assets and extravars resolved from a workload plugin."""

    setup_playbook: Optional[Path] = Field(
        default=None, description="Plugin setup playbook path"
    )
    teardown_playbook: Optional[Path] = Field(
        default=None, description="Plugin teardown playbook path"
    )
    setup_extravars: Dict[str, Any] = Field(
        default_factory=dict, description="Setup extravars"
    )
    teardown_extravars: Dict[str, Any] = Field(
        default_factory=dict, description="Teardown extravars"
    )
