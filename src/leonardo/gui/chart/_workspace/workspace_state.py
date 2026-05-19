from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class OscillatorSpec:
    key: str
    title: str


@dataclass
class OverlayStudyState:
    study_instance_id: str
    title: str
    render_keys: List[str]
    fill_ids: List[str] = field(default_factory=list)


@dataclass
class PricePaneState:
    """Workspace-owned view state for the canonical price pane.

    This state intentionally lives above the render surface so future updates
    can move vertical camera ownership out of the renderer without changing the
    surrounding workspace/pane contract again.
    """

    view_state: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OscillatorPaneState:
    pane_id: str
    study_instance_id: str
    title: str
    render_keys: List[str]
    preferred_height: int = 220
    visual_policy: Dict[str, Any] = field(default_factory=dict)
    view_state: Dict[str, Any] = field(default_factory=dict)

    # Workspace-owned cache for the resolved oscillator y-range.
    #
    # This avoids rescanning the same visible/resident windows on small camera
    # motion where the resolved range does not change.
    _y_range_cache_key: Optional[Tuple[Any, ...]] = None
    _y_range_cache_value: Optional[Tuple[float, float]] = None
