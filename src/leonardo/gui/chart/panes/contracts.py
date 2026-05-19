from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional


@dataclass(frozen=True)
class ManagedOverlayRowProjection:
    """
    Explicit price-pane projection for one managed overlay study row.

    This is a visualization-only projection consumed by PricePane.
    It is not study truth and it must not be treated as a registry entry.
    """
    study_instance_id: str
    title: str
    render_keys: List[str]


@dataclass(frozen=True)
class PaneBackgroundRegion:
    """
    Explicit price-pane background x-region consumed by the price renderer.

    Indices are resident-local and inclusive. Workspace/pane handoff remains
    resident-local; the renderer maps the local span back to chart-space through
    the explicit resident_base_index it already receives in the same contract.

    This payload is visual execution intent only. It is not study truth, not a
    chart series, and it must not affect price autoscale.
    """
    region_id: str
    start_index: int
    end_index: int
    color: Optional[str] = None
    opacity: float = 0.08
    visible: bool = True
    source_signal: str = ""
    label: str = ""


def _shared_mutable_view_state(view_state: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the mutable view-state mapping shared across workspace, pane, and renderer.

    Final point-C ownership requires durable pane view state to remain owned
    upstream by the workspace while still allowing renderer gesture code to
    write transient interaction keys directly into that same mapping. The pane
    must therefore preserve the original dict object when one is supplied
    instead of rebinding to a fresh copy.

    Rules:
    - preserve the exact mapping object when upstream already provided a dict
    - create a new empty dict only when no mapping was supplied
    - materialize non-dict Mapping inputs into a dict because render surfaces
      need a mutable mapping for direct gesture write-back
    """
    if isinstance(view_state, dict):
        return view_state
    if view_state is None:
        return {}
    return dict(view_state)
