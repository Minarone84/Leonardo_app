from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from leonardo.gui.chart.model import OverlayFill, Series, SeriesStyle


@dataclass(frozen=True)
class SignalStyleDefaults:
    """
    Chart-local default visual style for one renderable signal.

    This is a defaults contract, not live runtime state.
    It is intended to seed series/style objects when a study is first applied.
    """
    color: Optional[str] = None
    line_width: int = 2
    line_style: str = "solid"
    visible: bool = True
    render_mode: str = "line"
    marker_shape: Optional[str] = None
    marker_size: int = 0
    marker_text: str = ""
    marker_text_color: Optional[str] = None
    marker_offset_px: int = 0


@dataclass(frozen=True)
class FillStyleDefaults:
    """
    Chart-local default visual style for one static fill region owned by a study.

    This remains renderer-facing and static in this phase.
    Dynamic / conditional fill logic will layer on later.
    """
    fill_key: str
    signal_a_role: str
    signal_b_role: str
    color: Optional[str] = None
    opacity: float = 0.15
    visible: bool = True


@dataclass(frozen=True)
class BackgroundRegionStyleDefaults:
    """
    Chart-local default visual style for a full-height background region
    driven by a non-renderable study state signal.

    This is a defaults contract only. It does not compute state runs and it does
    not draw anything; panel/style resolution turns resident-local style-driver
    state into explicit renderer payloads downstream.
    """
    region_key: str
    driver_signal: str
    color: Optional[str] = None
    opacity: float = 0.08
    visible: bool = True
    label: str = ""


@dataclass(frozen=True)
class StudyStyleDefaults:
    """
    Default chart-local style policy for one study type.

    - `study_key` is the normalized tool key, for example: sma, bb, hck, rsi
    - `signal_defaults` maps emitted signal names to visual defaults
    - `fill_defaults` defines optional static fill regions between signals
    """
    study_key: str
    signal_defaults: Dict[str, SignalStyleDefaults] = field(default_factory=dict)
    fill_defaults: List[FillStyleDefaults] = field(default_factory=list)
    background_region_defaults: List[BackgroundRegionStyleDefaults] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Single-line indicator defaults
# ---------------------------------------------------------------------------

SMA_DEFAULTS = StudyStyleDefaults(
    study_key="sma",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#F59E0B",  # amber
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

EMA_DEFAULTS = StudyStyleDefaults(
    study_key="ema",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#22C55E",  # green
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

TEMA_DEFAULTS = StudyStyleDefaults(
    study_key="tema",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#A855F7",  # purple
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

HMA_DEFAULTS = StudyStyleDefaults(
    study_key="hma",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#06B6D4",  # cyan
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

KAMA_DEFAULTS = StudyStyleDefaults(
    study_key="kama",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#EF4444",  # red
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

# ---------------------------------------------------------------------------
# Multi-line indicator defaults
# ---------------------------------------------------------------------------

BB_DEFAULTS = StudyStyleDefaults(
    study_key="bb",
    signal_defaults={
        "bb_middle": SignalStyleDefaults(
            color="#F59E0B",  # amber
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "bb_upper_band": SignalStyleDefaults(
            color="#60A5FA",  # blue-400
            line_width=1,
            line_style="dashed",
            visible=True,
        ),
        "bb_lower_band": SignalStyleDefaults(
            color="#60A5FA",  # blue-400
            line_width=1,
            line_style="dashed",
            visible=True,
        ),
    },
    fill_defaults=[
        FillStyleDefaults(
            fill_key="bb_band",
            signal_a_role="bb_upper_band",
            signal_b_role="bb_lower_band",
            color="#60A5FA",
            opacity=0.12,
            visible=True,
        ),
    ],
)

HCK_DEFAULTS = StudyStyleDefaults(
    study_key="hck",
    signal_defaults={
        "fast_vwap": SignalStyleDefaults(
            color="#22C55E",  # green
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "slow_vwap": SignalStyleDefaults(
            color="#EF4444",  # red
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
    fill_defaults=[
        FillStyleDefaults(
            fill_key="hck_band",
            signal_a_role="fast_vwap",
            signal_b_role="slow_vwap",
            color="#94A3B8",  # slate-400
            opacity=0.12,
            visible=True,
        ),
    ],
)

PEAKS_TROUGHS_DEFAULTS = StudyStyleDefaults(
    study_key="peaks_troughs",
    signal_defaults={
        "peak_fractal_3": SignalStyleDefaults(color="#22C55E", line_width=1, line_style="solid", visible=True, render_mode="marker", marker_shape="triangle_down", marker_size=14, marker_text="3", marker_text_color="#000000", marker_offset_px=-18),
        "trough_fractal_3": SignalStyleDefaults(color="#EF4444", line_width=1, line_style="solid", visible=True, render_mode="marker", marker_shape="triangle_up", marker_size=14, marker_text="3", marker_text_color="#000000", marker_offset_px=18),
        "peak_fractal_5": SignalStyleDefaults(color="#22C55E", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_down", marker_size=14, marker_text="5", marker_text_color="#000000", marker_offset_px=-18),
        "trough_fractal_5": SignalStyleDefaults(color="#EF4444", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_up", marker_size=14, marker_text="5", marker_text_color="#000000", marker_offset_px=18),
        "peak_fractal_7": SignalStyleDefaults(color="#22C55E", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_down", marker_size=14, marker_text="7", marker_text_color="#000000", marker_offset_px=-18),
        "trough_fractal_7": SignalStyleDefaults(color="#EF4444", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_up", marker_size=14, marker_text="7", marker_text_color="#000000", marker_offset_px=18),
        "peak_fractal_9": SignalStyleDefaults(color="#22C55E", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_down", marker_size=14, marker_text="9", marker_text_color="#000000", marker_offset_px=-18),
        "trough_fractal_9": SignalStyleDefaults(color="#EF4444", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_up", marker_size=14, marker_text="9", marker_text_color="#000000", marker_offset_px=18),
        "peak_fractal_11": SignalStyleDefaults(color="#22C55E", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_down", marker_size=14, marker_text="11", marker_text_color="#000000", marker_offset_px=-18),
        "trough_fractal_11": SignalStyleDefaults(color="#EF4444", line_width=1, line_style="solid", visible=False, render_mode="marker", marker_shape="triangle_up", marker_size=14, marker_text="11", marker_text_color="#000000", marker_offset_px=18),
    },
)

UNIVERSAL_TREND_CLASSIFIER_DEFAULTS = StudyStyleDefaults(
    study_key="universal_trend_classifier",
    background_region_defaults=[
        BackgroundRegionStyleDefaults(
            region_key="uptrend_background",
            driver_signal="uptrend",
            color="#22C55E",
            opacity=0.08,
            visible=True,
            label="Uptrend Background",
        ),
        BackgroundRegionStyleDefaults(
            region_key="downtrend_background",
            driver_signal="downtrend",
            color="#EF4444",
            opacity=0.08,
            visible=True,
            label="Downtrend Background",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Single-line bounded oscillator defaults
# ---------------------------------------------------------------------------

RSI_DEFAULTS = StudyStyleDefaults(
    study_key="rsi",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#A855F7",  # purple
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "rsi": SignalStyleDefaults(
            color="#A855F7",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

ARSI_DEFAULTS = StudyStyleDefaults(
    study_key="arsi",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#8B5CF6",  # violet
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "arsi": SignalStyleDefaults(
            color="#8B5CF6",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "signal": SignalStyleDefaults(
            color="#FF5D00",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "arsi_signal": SignalStyleDefaults(
            color="#FF5D00",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

MFI_DEFAULTS = StudyStyleDefaults(
    study_key="mfi",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#14B8A6",  # teal
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "mfi": SignalStyleDefaults(
            color="#14B8A6",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

# ---------------------------------------------------------------------------
# Multi-line bounded oscillator defaults
# ---------------------------------------------------------------------------

TDI_DEFAULTS = StudyStyleDefaults(
    study_key="tdi",
    signal_defaults={
        "pl": SignalStyleDefaults(
            color="#22C55E",  # green
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "price_line": SignalStyleDefaults(
            color="#22C55E",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "rsi": SignalStyleDefaults(
            color="#22C55E",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "tsl": SignalStyleDefaults(
            color="#EF4444",  # red
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "signal": SignalStyleDefaults(
            color="#EF4444",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "trade_signal_line": SignalStyleDefaults(
            color="#EF4444",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "mbl": SignalStyleDefaults(
            color="#F59E0B",  # amber
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "market_base_line": SignalStyleDefaults(
            color="#F59E0B",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "ub": SignalStyleDefaults(
            color="#60A5FA",  # blue-400
            line_width=1,
            line_style="dashed",
            visible=True,
        ),
        "upper_band": SignalStyleDefaults(
            color="#A855F7",
            line_width=1,
            line_style="dashed",
            visible=True,
        ),
        "lb": SignalStyleDefaults(
            color="#60A5FA",  # blue-400
            line_width=1,
            line_style="dashed",
            visible=True,
        ),
        "lower_band": SignalStyleDefaults(
            color="#A855F7",
            line_width=1,
            line_style="dashed",
            visible=True,
        ),
    },
    fill_defaults=[
        FillStyleDefaults(
            fill_key="tdi_band",
            signal_a_role="upper_band",
            signal_b_role="lower_band",
            color="#60A5FA",
            opacity=0.10,
            visible=True,
        ),
        FillStyleDefaults(
            fill_key="tdi_band_short",
            signal_a_role="ub",
            signal_b_role="lb",
            color="#60A5FA",
            opacity=0.10,
            visible=True,
        ),
    ],
)

# ---------------------------------------------------------------------------
# Multi-line signal oscillator defaults
# ---------------------------------------------------------------------------

SMI_DEFAULTS = StudyStyleDefaults(
    study_key="smi",
    signal_defaults={
        "smi": SignalStyleDefaults(
            color="#06B6D4",  # cyan
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "sig": SignalStyleDefaults(
            color="#F59E0B",  # amber
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "signal": SignalStyleDefaults(
            color="#F59E0B",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "__primary__": SignalStyleDefaults(
            color="#06B6D4",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)

# ---------------------------------------------------------------------------
# Unbounded cumulative oscillator defaults
# ---------------------------------------------------------------------------

OBV_DEFAULTS = StudyStyleDefaults(
    study_key="obv",
    signal_defaults={
        "__primary__": SignalStyleDefaults(
            color="#E5E7EB",  # gray-200
            line_width=1,
            line_style="solid",
            visible=True,
        ),
        "obv": SignalStyleDefaults(
            color="#E5E7EB",
            line_width=1,
            line_style="solid",
            visible=True,
        ),
    },
)


VOLUME_DEFAULTS = StudyStyleDefaults(
    study_key="volume",
    signal_defaults={
        "volume": SignalStyleDefaults(
            color="#22C55E",
            line_width=1,
            line_style="solid",
            visible=True,
            render_mode="histogram",
        ),
        # Period-specific runtime outputs use names such as volume_mean_20.
        # Style resolution maps those outputs to this prefix/default key.
        "volume_mean": SignalStyleDefaults(
            color="#06B6D4",  # cyan
            line_width=1,
            line_style="solid",
            visible=True,
            render_mode="line",
        ),
    },
)

# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

INDICATOR_STUDY_STYLE_DEFAULTS: Dict[str, StudyStyleDefaults] = {
    "sma": SMA_DEFAULTS,
    "ema": EMA_DEFAULTS,
    "tema": TEMA_DEFAULTS,
    "hma": HMA_DEFAULTS,
    "kama": KAMA_DEFAULTS,
    "bb": BB_DEFAULTS,
    "hck": HCK_DEFAULTS,
    "peaks_troughs": PEAKS_TROUGHS_DEFAULTS,
    "universal_trend_classifier": UNIVERSAL_TREND_CLASSIFIER_DEFAULTS,
}

OSCILLATOR_STUDY_STYLE_DEFAULTS: Dict[str, StudyStyleDefaults] = {
    "rsi": RSI_DEFAULTS,
    "arsi": ARSI_DEFAULTS,
    "mfi": MFI_DEFAULTS,
    "tdi": TDI_DEFAULTS,
    "smi": SMI_DEFAULTS,
    "obv": OBV_DEFAULTS,
    "volume": VOLUME_DEFAULTS,
}

STUDY_STYLE_DEFAULTS_REGISTRY: Dict[str, StudyStyleDefaults] = {
    **INDICATOR_STUDY_STYLE_DEFAULTS,
    **OSCILLATOR_STUDY_STYLE_DEFAULTS,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_study_style_defaults(study_key: str) -> StudyStyleDefaults:
    normalized = str(study_key).strip().lower()
    return STUDY_STYLE_DEFAULTS_REGISTRY.get(
        normalized,
        StudyStyleDefaults(study_key=normalized),
    )


def build_default_background_region_styles(study_key: str) -> List[BackgroundRegionStyleDefaults]:
    """Return chart-local default background-region styles for one study key."""
    defaults = get_study_style_defaults(study_key)
    return list(defaults.background_region_defaults)



def _signal_style_defaults_for(
    *,
    defaults: StudyStyleDefaults,
    signal_name: str,
) -> Optional[SignalStyleDefaults]:
    """Resolve signal defaults for canonical and parameterized emitted names."""
    normalized_signal = str(signal_name).strip()
    signal_defaults = defaults.signal_defaults.get(normalized_signal)
    if signal_defaults is not None:
        return signal_defaults

    study_key = str(defaults.study_key).strip().lower()

    def first_available(*keys: str) -> Optional[SignalStyleDefaults]:
        for key in keys:
            candidate = defaults.signal_defaults.get(key)
            if candidate is not None:
                return candidate
        return None

    if study_key == "rsi" and normalized_signal.startswith("rsi_"):
        return first_available("rsi", "__primary__")

    if study_key == "arsi":
        if normalized_signal.startswith("arsi_signal_"):
            return first_available("signal", "arsi_signal", "__primary__")
        if normalized_signal.startswith("arsi_"):
            return first_available("arsi", "__primary__")

    if study_key == "mfi" and normalized_signal.startswith("mfi_"):
        return first_available("mfi", "__primary__")

    if study_key == "smi":
        if normalized_signal.startswith("smi_signal_"):
            return first_available("signal", "sig", "__primary__")
        if normalized_signal.startswith("smi_"):
            return first_available("smi", "__primary__")

    if study_key in {"tdi", "tdirsi"}:
        if normalized_signal.startswith("tdirsi_fast_ma_"):
            return first_available("price_line", "pl")
        if normalized_signal.startswith("tdirsi_slow_ma_"):
            return first_available("trade_signal_line", "tsl", "signal")
        if normalized_signal.startswith("tdirsi_up_"):
            return first_available("upper_band", "ub")
        if normalized_signal.startswith("tdirsi_dn_"):
            return first_available("lower_band", "lb")
        if normalized_signal.startswith("tdirsi_mid_"):
            return first_available("market_base_line", "mbl")

    if study_key == "volume" and normalized_signal.startswith("volume_mean_"):
        return first_available("volume_mean")

    return defaults.signal_defaults.get("__primary__")


def get_signal_style_defaults(
    *,
    study_key: str,
    signal_name: str,
) -> Optional[SignalStyleDefaults]:
    """Resolve chart-local style defaults for one emitted study signal."""
    normalized_study_key = str(study_key).strip().lower()
    defaults_key = "tdi" if normalized_study_key == "tdirsi" else normalized_study_key
    defaults = get_study_style_defaults(defaults_key)
    return _signal_style_defaults_for(
        defaults=defaults,
        signal_name=signal_name,
    )

def build_default_series_style(
    *,
    study_key: str,
    signal_name: str,
) -> SeriesStyle:
    """
    Resolve the chart-local default SeriesStyle for one emitted signal.

    Resolution order:
    1. exact emitted signal name
    2. "__primary__" fallback for single-line studies
    3. generic SeriesStyle()
    """
    signal_defaults = get_signal_style_defaults(
        study_key=study_key,
        signal_name=signal_name,
    )

    if signal_defaults is None:
        return SeriesStyle()

    return SeriesStyle(
        color=signal_defaults.color,
        line_width=int(signal_defaults.line_width),
        line_style=str(signal_defaults.line_style),
        visible=bool(signal_defaults.visible),
        render_mode=str(getattr(signal_defaults, "render_mode", "line") or "line"),
        marker_shape=getattr(signal_defaults, "marker_shape", None),
        marker_size=int(getattr(signal_defaults, "marker_size", 0) or 0),
        marker_text=str(getattr(signal_defaults, "marker_text", "") or ""),
        marker_text_color=getattr(signal_defaults, "marker_text_color", None),
        marker_offset_px=int(getattr(signal_defaults, "marker_offset_px", 0) or 0),
    )


def _is_neutral_series_style_placeholder(style: Optional[SeriesStyle]) -> bool:
    """
    Return True when a SeriesStyle still carries only transport defaults.

    `Series` always carries a `SeriesStyle()` instance by default, so a caller
    cannot rely on `None` to mean “unstyled”. Without this helper, non-color
    study defaults such as dashed band lines would be silently masked by the
    neutral transport values `line_width=1`, `line_style="solid"`, and
    `visible=True`.

    A style is therefore treated as unresolved only when all of these are true:
    - no explicit color
    - width is the neutral default 1
    - line style is the neutral default "solid"
    - visibility is the neutral default True
    """
    if style is None:
        return True

    color = str(getattr(style, "color", "") or "").strip()

    try:
        line_width = int(getattr(style, "line_width", 1) or 1)
    except Exception:
        line_width = 1

    line_style = str(getattr(style, "line_style", "solid") or "solid").strip().lower()
    visible = bool(getattr(style, "visible", True))
    render_mode = str(getattr(style, "render_mode", "line") or "line").strip().lower()
    marker_shape = str(getattr(style, "marker_shape", "") or "").strip().lower()
    marker_size = int(getattr(style, "marker_size", 0) or 0)
    marker_text = str(getattr(style, "marker_text", "") or "").strip()
    marker_text_color = str(getattr(style, "marker_text_color", "") or "").strip()
    marker_offset_px = int(getattr(style, "marker_offset_px", 0) or 0)

    return (
        (not color)
        and line_width == 1
        and line_style == "solid"
        and visible is True
        and render_mode == "line"
        and not marker_shape
        and marker_size == 0
        and not marker_text
        and not marker_text_color
        and marker_offset_px == 0
    )


def apply_default_styles_to_series_list(
    *,
    study_key: str,
    series_list: List[Series],
) -> List[Series]:
    """
    Return a new series list with chart-local default styles applied.

    Existing non-empty style values are preserved where possible so this helper
    can be used safely in both:
    - initial study application
    - later refresh/rebuild flows

    Important compatibility rule:
    neutral transport defaults coming from `SeriesStyle()` do not count as an
    explicit study style override. Otherwise dashed/default band styling would
    never land on first apply because every incoming `Series` already carries a
    placeholder `SeriesStyle` instance.
    """
    normalized_study_key = str(study_key).strip().lower()
    styled: List[Series] = []

    for series in series_list:
        default_style = build_default_series_style(
            study_key=normalized_study_key,
            signal_name=series.key.rsplit("|", 1)[-1].strip(),
        )

        existing = series.style if series.style is not None else SeriesStyle()

        if _is_neutral_series_style_placeholder(existing):
            resolved_style = SeriesStyle(
                color=default_style.color,
                line_width=int(default_style.line_width),
                line_style=str(default_style.line_style),
                visible=bool(default_style.visible),
                render_mode=str(getattr(default_style, "render_mode", "line") or "line"),
                marker_shape=getattr(default_style, "marker_shape", None),
                marker_size=int(getattr(default_style, "marker_size", 0) or 0),
                marker_text=str(getattr(default_style, "marker_text", "") or ""),
                marker_text_color=getattr(default_style, "marker_text_color", None),
                marker_offset_px=int(getattr(default_style, "marker_offset_px", 0) or 0),
            )
        else:
            color = existing.color if existing.color else default_style.color
            line_width = int(existing.line_width) if getattr(existing, "line_width", None) is not None else default_style.line_width
            line_style = str(existing.line_style) if getattr(existing, "line_style", None) else default_style.line_style
            visible = bool(getattr(existing, "visible", default_style.visible))
            render_mode = str(getattr(existing, "render_mode", None) or getattr(default_style, "render_mode", "line") or "line")

            marker_shape_value = getattr(existing, "marker_shape", None)
            marker_shape = marker_shape_value if marker_shape_value is not None else getattr(default_style, "marker_shape", None)

            marker_size_value = getattr(existing, "marker_size", None)
            marker_size = int(marker_size_value) if marker_size_value is not None else int(getattr(default_style, "marker_size", 0) or 0)

            marker_text_value = getattr(existing, "marker_text", None)
            marker_text = str(marker_text_value) if marker_text_value is not None else str(getattr(default_style, "marker_text", "") or "")

            marker_text_color_value = getattr(existing, "marker_text_color", None)
            marker_text_color = marker_text_color_value if marker_text_color_value is not None else getattr(default_style, "marker_text_color", None)

            marker_offset_px_value = getattr(existing, "marker_offset_px", None)
            marker_offset_px = int(marker_offset_px_value) if marker_offset_px_value is not None else int(getattr(default_style, "marker_offset_px", 0) or 0)

            resolved_style = SeriesStyle(
                color=color,
                line_width=line_width,
                line_style=line_style,
                visible=visible,
                render_mode=render_mode,
                marker_shape=marker_shape,
                marker_size=marker_size,
                marker_text=marker_text,
                marker_text_color=marker_text_color,
                marker_offset_px=marker_offset_px,
            )

        if series.style == resolved_style:
            styled.append(series)
        else:
            styled.append(
                Series(
                    key=series.key,
                    title=series.title,
                    values=series.values,
                    style=resolved_style,
                )
            )

    return styled


def build_default_overlay_fills(
    *,
    study_instance_id: str,
    study_key: str,
    series_list: List[Series],
) -> List[OverlayFill]:
    """
    Build static default overlay fills for a managed overlay study.

    Matching is based on emitted runtime signal names, which are encoded as the
    trailing component of the chart series key: "<tool>|<params>|<line_key>".
    """
    defaults = get_study_style_defaults(study_key)
    if not defaults.fill_defaults:
        return []

    by_signal_name: Dict[str, Series] = {
        series.key.rsplit("|", 1)[-1].strip(): series
        for series in series_list
    }

    fills: List[OverlayFill] = []
    for fill_default in defaults.fill_defaults:
        series_a = by_signal_name.get(fill_default.signal_a_role)
        series_b = by_signal_name.get(fill_default.signal_b_role)
        if series_a is None or series_b is None:
            continue

        fills.append(
            OverlayFill(
                fill_id=f"{study_instance_id}|fill|{fill_default.fill_key}",
                series_a=series_a.key,
                series_b=series_b.key,
                color=fill_default.color,
                opacity=float(fill_default.opacity),
                visible=bool(fill_default.visible),
            )
        )

    return fills
