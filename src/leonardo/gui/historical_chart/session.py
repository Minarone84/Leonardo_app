from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd

from leonardo.common.market_types import Candle as GuiCandle
from leonardo.data.historical.dataset_service import DatasetId
from leonardo.gui.chart.model import Series as ChartSeries


@dataclass(slots=True)
class StoredStudyLine:
    """Full-dataset runtime line retained as study truth inside the chart session.

    Renderability and analysis usability are copied from the resolved tool
    contract metadata so downstream source selection can expose analysis-usable
    runtime truth without turning it into chart render series.
    """

    key: str
    title: str
    values: pd.Series
    renderable: bool = False
    analysis_usable: bool = False
    can_drive_style_rules: bool = False
    signal_type: str = ""
    semantic_role: str = ""
    value_type: str = ""


@dataclass(slots=True)
class AppliedStudyProjection:
    """Controller-owned study cache entry.

    The controller must retain full-dataset study truth separately from the
    current resident-local projection. The projected ChartSeries list is a
    disposable render artifact that can be rebuilt whenever the resident window
    changes.
    """

    projection_key: str
    tool_type: str
    tool_key: str
    tool_title: str
    display_name: str
    params: Dict[str, Any]
    behavior: Dict[str, Any]
    output: Dict[str, Any]
    # Renderable chart-study lines.  These are the only full-dataset lines that
    # may become projected chart series.
    full_lines: list[StoredStudyLine] = field(default_factory=list)

    # Non-renderable state lines used only by chart-local style modules.  They
    # are projected for panel-owned visual derivation, never as chart series.
    full_style_driver_lines: list[StoredStudyLine] = field(default_factory=list)

    # Non-renderable analysis-usable lines retained for temporary construct
    # chaining.  They remain full-dataset source truth and are never projected
    # into renderer-facing chart payloads.
    full_analysis_source_lines: list[StoredStudyLine] = field(default_factory=list)

    projected_series_list: list[ChartSeries] = field(default_factory=list)
    projected_style_driver_series_list: list[ChartSeries] = field(default_factory=list)


@dataclass(slots=True)
class ChartDataSession:
    """Central controller-owned chart-session data authority.

    This state object intentionally separates:
    - canonical dataset/session identity
    - canonical full-dataset truth
    - resident window state
    - timeline helpers
    - full study truth
    - resident-local projected study payloads

    It does not own viewport or pane policy. Those remain downstream.
    """

    dataset_id: Optional[DatasetId] = None
    dataset_count: Optional[int] = None
    timeline_ts_ms: list[int] = field(default_factory=list)
    timeline_index_by_ts_ms: dict[int, int] = field(default_factory=dict)
    full_dataset_df: Optional[pd.DataFrame] = None
    resident_base_index: int = 0
    resident_size: int = 0
    resident_candles: list[GuiCandle] = field(default_factory=list)
    has_more_left: bool = False
    has_more_right: bool = False
    studies_by_projection_key: dict[str, AppliedStudyProjection] = field(default_factory=dict)

    def reset_for_dataset(self, dataset_id: DatasetId) -> None:
        self.dataset_id = dataset_id
        self.dataset_count = None
        self.timeline_ts_ms.clear()
        self.timeline_index_by_ts_ms.clear()
        self.full_dataset_df = None
        self.resident_base_index = 0
        self.resident_size = 0
        self.resident_candles.clear()
        self.has_more_left = False
        self.has_more_right = False
        self.studies_by_projection_key.clear()

    def set_dataset_count(self, dataset_count: Optional[int]) -> None:
        self.dataset_count = None if dataset_count is None else int(dataset_count)

    def set_timeline(self, timeline_ts_ms: list[int]) -> None:
        normalized = [int(ts) for ts in timeline_ts_ms]
        for idx in range(1, len(normalized)):
            if normalized[idx] <= normalized[idx - 1]:
                raise ValueError("ChartDataSession timeline must be strictly increasing.")

        self.timeline_ts_ms = normalized
        self.timeline_index_by_ts_ms = {ts: idx for idx, ts in enumerate(normalized)}
        if normalized:
            self.dataset_count = len(normalized)

    def cache_full_dataset_dataframe(self, df: pd.DataFrame) -> None:
        cached = df.copy(deep=True)
        self.full_dataset_df = cached
        if not cached.empty and "ts_ms" in cached.columns:
            self.set_timeline(cached["ts_ms"].astype("int64").tolist())
        elif self.dataset_count is None:
            self.dataset_count = len(cached)

    def get_cached_full_dataset_dataframe(self) -> Optional[pd.DataFrame]:
        if self.full_dataset_df is None:
            return None
        return self.full_dataset_df.copy(deep=True)

    def set_resident_slice(
        self,
        *,
        base_index: int,
        candles: list[GuiCandle],
        has_more_left: bool,
        has_more_right: bool,
    ) -> None:
        self.resident_base_index = int(base_index)
        self.resident_candles = list(candles)
        self.resident_size = len(candles)
        self.has_more_left = bool(has_more_left)
        self.has_more_right = bool(has_more_right)

    def ts_ms_to_global_index(self, ts_ms: int) -> Optional[int]:
        return self.timeline_index_by_ts_ms.get(int(ts_ms))

    def global_index_to_ts_ms(self, global_index: int) -> Optional[int]:
        idx = int(global_index)
        if 0 <= idx < len(self.timeline_ts_ms):
            return int(self.timeline_ts_ms[idx])
        return None
