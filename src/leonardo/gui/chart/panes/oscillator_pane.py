from __future__ import annotations

from html import escape
from typing import Any, List, Mapping, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from leonardo.gui.chart.crosshair import Crosshair
from leonardo.gui.chart.model import Series
from leonardo.gui.chart.series_render import OscillatorRenderSurface
from leonardo.gui.chart.viewport import ChartViewport

from .contracts import _shared_mutable_view_state
from .header_widgets import _PaneOverlay

class OscillatorPane(QWidget):
    """
    Managed oscillator pane.

    Final-contract intent for point C:
    - oscillator study truth lives outside the renderer and arrives here as
      explicit render series, pane policy, and workspace-owned pane view state
    - the pane is the explicit handoff boundary into the render surface and
      must not fork a second durable view-state owner
    - the renderer consumes explicit pane inputs and should not infer ownership
      or registry semantics on its own

    Oscillator studies remain auxiliary analytical panes rendered against the
    same chart-session x-axis as the base OHLC layer.
    """

    study_style_requested = Signal(str)
    study_edit_requested = Signal(str)
    study_remove_requested = Signal(str)
    pane_move_up_requested = Signal(str)
    pane_move_down_requested = Signal(str)

    def __init__(
        self,
        title: str,
        viewport: ChartViewport,
        crosshair: Crosshair,
        values: Optional[List[float]] = None,
        *,
        study_instance_id: str = "",
        series_list: Optional[List[Series]] = None,
        visual_policy: Optional[Mapping[str, Any]] = None,
        view_state: Optional[Mapping[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._title_text = str(title).strip() or "Oscillator"
        self._study_instance_id = str(study_instance_id).strip()
        self._viewport = viewport
        self._crosshair = crosshair
        self._resident_base_index = 0
        self._visual_policy: dict[str, Any] = dict(visual_policy or {})
        self._view_state: dict[str, Any] = _shared_mutable_view_state(view_state)
        self._last_overlay_text = ""
        self._overlay_layout_dirty = True

        if series_list:
            # Series is a frozen dataclass; treat it as immutable transport and
            # avoid rebuilding wrapper objects in the hot path.
            self._series_list = series_list if isinstance(series_list, list) else list(series_list)
        else:
            self._series_list = [
                Series(
                    key="__oscillator__",
                    title=self._title_text,
                    values=values if hasattr(values, "__len__") and hasattr(values, "__getitem__") else [],
                )
            ]

        self._surface = OscillatorRenderSurface(
            title=self._title_text,
            viewport=self._viewport,
            crosshair=self._crosshair,
            values=self._primary_values(),
            parent=self,
            visual_policy=self._visual_policy,
        )
        self._overlay = _PaneOverlay(self)

        self._header_host = QWidget(self._overlay)
        self._header_layout = QHBoxLayout(self._header_host)
        self._header_layout.setContentsMargins(0, 0, 0, 0)
        self._header_layout.setSpacing(4)

        self._title = QLabel(self._title_text, self._header_host)
        self._header_layout.addWidget(self._title, 1)

        self._move_up_btn = QToolButton(self._header_host)
        self._move_up_btn.setText("↑")
        self._move_up_btn.setToolTip("Move oscillator pane up")
        self._move_up_btn.clicked.connect(self._emit_move_up)
        self._header_layout.addWidget(self._move_up_btn, 0)

        self._move_down_btn = QToolButton(self._header_host)
        self._move_down_btn.setText("↓")
        self._move_down_btn.setToolTip("Move oscillator pane down")
        self._move_down_btn.clicked.connect(self._emit_move_down)
        self._header_layout.addWidget(self._move_down_btn, 0)

        self._style_btn = QToolButton(self._header_host)
        self._style_btn.setText("Style")
        self._style_btn.setToolTip("Edit display style")
        self._style_btn.clicked.connect(self._emit_style)
        self._header_layout.addWidget(self._style_btn, 0)

        self._edit_btn = QToolButton(self._header_host)
        self._edit_btn.setText("Edit")
        self._edit_btn.setToolTip("Edit computation parameters")
        self._edit_btn.clicked.connect(self._emit_edit)
        self._header_layout.addWidget(self._edit_btn, 0)

        self._remove_btn = QToolButton(self._header_host)
        self._remove_btn.setText("X")
        self._remove_btn.setToolTip("Remove oscillator study from chart")
        self._remove_btn.clicked.connect(self._emit_remove)
        self._header_layout.addWidget(self._remove_btn, 0)

        self._line1 = QLabel("", self._overlay)

        overlay_layout = self._overlay.layout_box
        overlay_layout.addWidget(self._header_host)
        overlay_layout.addWidget(self._line1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._crosshair.changed.connect(self._update_overlay)
        self._crosshair.cleared.connect(self._update_overlay)

        self._sync_surface_state()
        self._update_overlay()

    @property
    def study_instance_id(self) -> str:
        return self._study_instance_id

    def apply_view_state_contract(self, view_state: Optional[Mapping[str, Any]]) -> None:
        """Apply the workspace-owned oscillator view state as a narrow contract update.

        Used for viewport-driven y-range reconciliation. Preserves the shared mutable
        mapping so renderer gesture write-back lands in the same workspace-owned state.
        """
        self._view_state = _shared_mutable_view_state(view_state)
        self._sync_surface_state()

    def view_state_snapshot(self) -> dict[str, Any]:
        return dict(self._view_state)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_overlay_geometry(force=True)

    def _refresh_overlay_geometry(self, *, force: bool = False) -> None:
        """Resize the floating overlay only when layout is dirty.

        Overlay widgets are relatively expensive because they trigger Qt
        layout work. This pane therefore avoids calling adjustSize() on
        routine crosshair/value updates and reserves geometry refresh for
        structural changes such as title updates.
        """
        if force or self._overlay_layout_dirty:
            self._overlay.anchor_top_left()
            self._overlay_layout_dirty = False

    def set_move_capabilities(self, *, can_move_up: bool, can_move_down: bool) -> None:
        self._move_up_btn.setEnabled(bool(can_move_up))
        self._move_down_btn.setEnabled(bool(can_move_down))

    def apply_workspace_contract(
        self,
        *,
        study_instance_id: str,
        title: str,
        series_list: List[Series],
        visual_policy: Optional[Mapping[str, Any]],
        view_state: Optional[Mapping[str, Any]],
        resident_base_index: int,
    ) -> None:
        """Apply the full workspace-owned oscillator-pane contract in one handoff."""
        self._study_instance_id = str(study_instance_id).strip()
        self._title_text = str(title).strip() or "Oscillator"
        self._title.setText(self._title_text)
        self._overlay_layout_dirty = True
        self._refresh_overlay_geometry(force=True)
        self._series_list = series_list if isinstance(series_list, list) else list(series_list)
        self._visual_policy = dict(visual_policy or {})
        self._view_state = _shared_mutable_view_state(view_state)
        self._resident_base_index = max(0, int(resident_base_index))
        self._sync_surface_state()
        self._update_overlay()

    def _primary_series(self) -> Optional[Series]:
        if not self._series_list:
            return None
        return self._series_list[0]

    def _primary_values(self) -> List[float]:
        primary = self._primary_series()
        if primary is None:
            return []
        return primary.values

    def _sync_surface_state(self) -> None:
        # Contract-first handoff. OscillatorRenderSurface consumes an explicit
        # series/policy/view-state contract from workspace/pane ownership.
        self._surface.apply_contract(
            title=self._title_text,
            series_list=self._series_list,
            visual_policy=self._visual_policy,
            view_state=self._view_state,
            resident_base_index=self._resident_base_index,
        )

    def _global_to_local(self, global_index: int) -> Optional[int]:
        primary = self._primary_series()
        if primary is None:
            return None

        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(primary.values):
            return local
        return None

    def _overlay_index_local(self) -> Optional[int]:
        primary = self._primary_series()
        if primary is None or not primary.values:
            return None

        idx = self._crosshair.index
        local = self._global_to_local(idx) if idx is not None else None
        if local is None:
            local = len(primary.values) - 1
        return local

    def _series_label_for_overlay(self, series: Series) -> str:
        line_key = self._line_key_for_series(series)
        if line_key:
            known = self._known_overlay_acronym_for_line_key(line_key)
            if known:
                return known

        full = str(series.title).strip()
        if not full:
            return "VAL"

        if "·" in full:
            tail = full.rsplit("·", 1)[-1].strip()
            if tail:
                compact = self._compact_overlay_label(tail)
                if compact:
                    return compact

        if "[" in full and "]" in full:
            head = full.split("]", 1)[-1].strip()
            if head:
                compact = self._compact_overlay_label(head)
                if compact:
                    return compact

        compact = self._compact_overlay_label(full)
        return compact or "VAL"

    def _line_key_for_series(self, series: Series) -> str:
        key_text = str(getattr(series, "key", "") or "").strip()
        if not key_text:
            return ""
        return key_text.rsplit("|", 1)[-1].strip().lower()

    def _known_overlay_acronym_for_line_key(self, line_key: str) -> str:
        normalized = str(line_key).strip().lower()
        if not normalized:
            return ""

        known = {
            "tdirsi_fast_ma": "PL",
            "tdirsi_slow_ma": "TSL",
            "tdirsi_mid_band": "MBL",
            "tdirsi_upper_band": "UB",
            "tdirsi_lower_band": "LB",
            "smi_signal": "SIG",
            "obv": "OBV",
        }
        if normalized in known:
            return known[normalized]

        if normalized.startswith("rsi_"):
            return "RSI"
        if normalized.startswith("arsi_"):
            return "ARSI"
        if normalized.startswith("mfi_"):
            return "MFI"
        if normalized.startswith("smi_"):
            return "SMI"

        return ""

    def _compact_overlay_label(self, text: str) -> str:
        raw = str(text).strip()
        if not raw:
            return ""

        parts = [part for part in raw.replace("-", " ").replace("_", " ").split() if part]
        if not parts:
            return ""

        if len(parts) == 1:
            token = parts[0]
            letters = "".join(ch for ch in token if ch.isalpha())
            digits = "".join(ch for ch in token if ch.isdigit())
            if letters and len(letters) <= 5:
                return (letters.upper() + digits)[:8]
            return token[:8].upper()

        acronym = "".join(part[0].upper() for part in parts if part)
        return acronym[:8]

    def _series_color_for_overlay(self, series: Series) -> str:
        style = getattr(series, "style", None)
        color_text = str(getattr(style, "color", "") or "").strip()
        if color_text:
            return color_text
        return "#FFFFFF"

    def _format_value(self, value: float) -> str:
        try:
            numeric = float(value)
        except Exception:
            return "—"

        if numeric != numeric:
            return "—"

        return f"{numeric:.2f}"


    _BRAIDS_AMBIENT_VALUE_MAP: Mapping[int, str] = {
        1: "1: S>M>F",
        2: "2: S>F>M",
        3: "3: F>S>M",
        4: "4: F>M>S",
        5: "5: M>F>S",
        6: "6: M>S>F",
    }

    def _format_value_for_series(self, series: Series, value: Any) -> str:
        """Format overlay value text with small tool-aware adaptations.

        Important: this is display-only. It does not mutate series values and it
        does not affect computation truth.
        """
        title = str(getattr(series, "title", "") or "").strip().lower()
        if "braid" in title and "ambient" in title and "state" in title:
            try:
                numeric = float(value)
            except Exception:
                return "—"

            if numeric != numeric:
                return "—"

            code = int(round(numeric))
            return self._BRAIDS_AMBIENT_VALUE_MAP.get(code, "—")

        return self._format_value(value)

    def _build_overlay_fragment_html(self, *, label: str, value_text: str, color: str) -> str:
        safe_label = escape(str(label))
        safe_value = escape(str(value_text))
        safe_color = escape(str(color or "#FFFFFF"))
        return (
            f'<span style="color:{safe_color};">'
            f"{safe_label}: {safe_value}"
            f"</span>"
        )

    def _update_overlay(self) -> None:
        local_idx = self._overlay_index_local()
        if local_idx is None:
            if self._last_overlay_text != "—":
                self._line1.setText("—")
                self._last_overlay_text = "—"
            return

        fragments: List[str] = []
        for idx, series in enumerate(self._series_list):
            if local_idx >= len(series.values):
                continue

            value_text = self._format_value_for_series(series, series.values[local_idx])
            if len(self._series_list) == 1 and idx == 0:
                fragments.append(value_text)
            else:
                fragments.append(
                    self._build_overlay_fragment_html(
                        label=self._series_label_for_overlay(series),
                        value_text=value_text,
                        color=self._series_color_for_overlay(series),
                    )
                )

        text = "  |  ".join(fragments) if fragments else "—"
        if text != self._last_overlay_text:
            self._line1.setText(text)
            self._last_overlay_text = text

    def _emit_style(self) -> None:
        if self._study_instance_id:
            self.study_style_requested.emit(self._study_instance_id)

    def _emit_edit(self) -> None:
        if self._study_instance_id:
            self.study_edit_requested.emit(self._study_instance_id)

    def _emit_remove(self) -> None:
        if self._study_instance_id:
            self.study_remove_requested.emit(self._study_instance_id)

    def _emit_move_up(self) -> None:
        if self._study_instance_id:
            self.pane_move_up_requested.emit(self._study_instance_id)

    def _emit_move_down(self) -> None:
        if self._study_instance_id:
            self.pane_move_down_requested.emit(self._study_instance_id)
