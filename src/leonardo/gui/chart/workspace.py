from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QWidget, QVBoxLayout

from leonardo.gui.chart.crosshair import Crosshair
from leonardo.gui.chart.model import ChartModel
from leonardo.gui.chart.panes import OscillatorPane, PricePane, VolumePane
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart._workspace.workspace_apply import WorkspaceApplyMixin
from leonardo.gui.chart._workspace.workspace_autoscale import WorkspaceAutoscaleMixin
from leonardo.gui.chart._workspace.workspace_batches import WorkspaceBatchMixin
from leonardo.gui.chart._workspace.workspace_contracts import WorkspaceContractMixin
from leonardo.gui.chart._workspace.workspace_oscillators import WorkspaceOscillatorMixin
from leonardo.gui.chart._workspace.workspace_overlays import WorkspaceOverlayMixin
from leonardo.gui.chart._workspace.workspace_state import (
    OscillatorPaneState,
    OscillatorSpec,
    OverlayStudyState,
    PricePaneState,
)


class ChartWorkspaceWidget(
    QWidget,
    WorkspaceApplyMixin,
    WorkspaceAutoscaleMixin,
    WorkspaceBatchMixin,
    WorkspaceContractMixin,
    WorkspaceOscillatorMixin,
    WorkspaceOverlayMixin,
):
    """
    Central chart workspace: price pane + optional volume + optional oscillator panes.

    Final point-C workspace contract:
    - ChartModel owns the canonical base OHLC layer and study truth currently
      resident in the GUI process.
    - ChartViewport owns the shared horizontal camera only.
    - Workspace owns pane layout, pane lifecycle, pane view state, and the
      explicit projection payloads pushed into panes.
    - Panes consume workspace-owned state and hand explicit render inputs to
      render surfaces.
    - Render surfaces must not discover pane grouping or pane ownership by
      inspecting workspace internals.

    apply_snapshot/apply_patch remain the GUI-thread entry points for core
    market-data updates.
    """

    request_start_feed = Signal()
    request_stop_feed = Signal()

    # Fixed chart-space padding for historical sessions. This is part of the
    # chart environment contract owned by the workspace, not a side effect of
    # viewport anchoring behavior.
    HISTORICAL_LEFT_DOMAIN_PAD = 1000
    HISTORICAL_RIGHT_DOMAIN_PAD = 1000

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._crosshair = Crosshair()

        # ---- Shared data (owned by the model) ----
        self._model = ChartModel(candles=[], volume=[])

        # ---- Shared viewport ----
        self._viewport = ChartViewport(total_count=0, visible_count=1)

        # ---- Layout ----
        self._splitter = QSplitter(Qt.Vertical, self)
        self._splitter.setChildrenCollapsible(False)

        self._price_state = PricePaneState()

        # Workspace owns the price-pane vertical contract. This is distinct
        # from viewport zoom-anchor behavior, even while older callers still
        # enter through the legacy set_anchor_zoom_enabled() API. Keep the
        # canonical autoscale flag mirrored into the shared price-pane view
        # state so pane/render gesture logic does not have to infer vertical
        # ownership from the horizontal viewport compatibility flag.
        self._price_autoscale_enabled: bool = True
        self._price_state.view_state["autoscale_enabled"] = True

        self._price = PricePane(
            viewport=self._viewport,
            model=self._model,
            crosshair=self._crosshair,
            view_state=self._price_state.view_state,
            parent=self,
        )
        self._splitter.addWidget(self._price)

        # Optional panes (not shown by default)
        self._volume: Optional[VolumePane] = None

        # Managed overlay study state.
        # Transitional note:
        # This remains here for now, but it is no longer consumed implicitly by
        # the price pane. Workspace pushes an explicit row projection instead.
        self._overlay_states_by_id: Dict[str, OverlayStudyState] = {}
        self._overlay_render_key_to_study_id: Dict[str, str] = {}

        # Managed oscillator pane state.
        #
        # Final point-C rule in this workspace:
        # compatibility entry points may still exist for older callers, but all
        # oscillator-pane ownership must flow through this single managed pane
        # registry. Workspace must not keep a second legacy pane map alive.
        self._oscillator_panes_by_id: Dict[str, OscillatorPane] = {}
        self._oscillator_states_by_id: Dict[str, OscillatorPaneState] = {}
        self._oscillator_pane_order: List[str] = []
        self._study_to_pane_id: Dict[str, str] = {}

        # Workspace owns when chart-wide pane contracts should be refreshed.
        # Large resident-slice and multi-study updates therefore defer visual
        # fan-out until the final coherent workspace/model state is ready.
        self._workspace_update_depth: int = 0
        self._deferred_contract_refresh: bool = False
        self._deferred_labels_refresh: bool = False
        self._deferred_size_refresh: bool = False
        self._deferred_price_refresh: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._splitter)

        # Viewport changes are camera-only, but camera movement still changes
        # viewport-dependent pane contracts such as visible-range y-resolution.
        # Workspace owns that reconciliation step instead of leaving renderers to
        # rediscover vertical truth on their own.
        self._viewport.viewport_changed.connect(self._on_viewport_changed)

        self._apply_default_sizes(force=True)

    def set_asset_label(self, text: str) -> None:
        self._price.set_asset_label(text)

    def set_studies_labels(self, indicators: List[str], oscillators: List[str]) -> None:
        self._price.set_studies(indicators=indicators, oscillators=oscillators)
        self._sync_price_pane_contract()
        self._refresh_price_pane()

    @property
    def viewport(self) -> ChartViewport:
        return self._viewport

    @property
    def model(self) -> ChartModel:
        return self._model


__all__ = [
    "ChartWorkspaceWidget",
    "OscillatorSpec",
    "OverlayStudyState",
    "PricePaneState",
    "OscillatorPaneState",
]
