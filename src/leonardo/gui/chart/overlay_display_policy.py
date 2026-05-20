from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class OverlayStudyDisplayPolicy:
    """Chart-local display policy for compact price-pane overlay rows."""

    tool_key: str
    compact_label: str
    values_allowed: bool
    values_default_expanded: bool


_POLICY_LABELS: dict[str, str] = {
    "sma": "S",
    "ema": "E",
    "tema": "TEMA",
    "hma": "HMA",
    "kama": "KAMA",
    "bb": "BB",
    "hck": "HCK",
    "strategy": "STR",
    "peaks_troughs": "P/T",
    "universal_trend_classifier": "UTC",
    "utc": "UTC",
}

_VALUE_DISABLED_TOOLS = {
    "peaks_troughs",
    "universal_trend_classifier",
    "utc",
}

_KNOWN_TOOL_KEYS = set(_POLICY_LABELS)


def line_key_from_render_key(render_key: object) -> str:
    """Return the resident signal key carried by a render key."""
    text = str(render_key or "").strip()
    if not text:
        return ""
    return text.rsplit("|", 1)[-1].strip()


def infer_tool_key_from_render_keys(
    render_keys: Sequence[object],
    *,
    title: str = "",
) -> str:
    """Infer a compact-display tool key from render keys and title text."""
    for render_key in render_keys:
        parts = [part.strip() for part in str(render_key or "").split("|") if part.strip()]
        if len(parts) > 1:
            candidate = _normalize_tool_key(parts[0])
            if candidate in _KNOWN_TOOL_KEYS:
                return candidate

    line_keys = [line_key_from_render_key(render_key) for render_key in render_keys]
    inferred = _infer_tool_key_from_line_keys(line_keys)
    if inferred:
        return inferred

    return _infer_tool_key_from_title(title)


def build_overlay_study_display_policy(
    *,
    title: str,
    render_keys: Sequence[object],
) -> OverlayStudyDisplayPolicy:
    """Build the compact display policy for one price-pane overlay row."""
    tool_key = infer_tool_key_from_render_keys(render_keys, title=title)
    line_keys = [line_key_from_render_key(render_key) for render_key in render_keys]
    compact_label = _compact_study_label(tool_key, title=title, line_keys=line_keys)
    values_allowed = tool_key not in _VALUE_DISABLED_TOOLS
    return OverlayStudyDisplayPolicy(
        tool_key=tool_key,
        compact_label=compact_label,
        values_allowed=values_allowed,
        values_default_expanded=False,
    )


def compact_signal_label(tool_key: str, line_key: str) -> str:
    """Return a compact human-facing value label for an overlay signal."""
    normalized_tool = _normalize_tool_key(tool_key)
    normalized_line = str(line_key or "").strip()

    if normalized_tool == "strategy":
        label = _strategy_signal_label(normalized_line)
        if label:
            return label

    if normalized_line in {"bb_upper_band", "st_bb_upper_band"}:
        return "U"
    if normalized_line in {"bb_middle", "st_bb_middle"}:
        return "M"
    if normalized_line in {"bb_lower_band", "st_bb_lower_band"}:
        return "L"

    if normalized_line in {"fast_vwap", "st_fast_vwap"}:
        return "F"
    if normalized_line in {"slow_vwap", "st_slow_vwap"}:
        return "S"
    if normalized_line in {"vwap_color", "st_vwap_color"}:
        return ""

    if normalized_tool in {"sma", "ema", "tema", "hma", "kama"}:
        return ""

    return _fallback_signal_label(normalized_line)


def _normalize_tool_key(text: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower())
    normalized = normalized.strip("_")
    if normalized == "utc":
        return "universal_trend_classifier"
    return normalized


def _infer_tool_key_from_line_keys(line_keys: Iterable[str]) -> str:
    for line_key in line_keys:
        line = str(line_key or "").strip()
        if not line:
            continue
        if line.startswith("st_"):
            return "strategy"
        if line.startswith("peak_") or line.startswith("trough_"):
            return "peaks_troughs"
        if line in {
            "hor_upper",
            "hor_lower",
            "hr_start_marker",
            "hr_end_marker",
            "uptrend_start_marker",
            "uptrend_end_marker",
            "downtrend_start_marker",
            "downtrend_end_marker",
        }:
            return "universal_trend_classifier"
        if line.startswith("bb_"):
            return "bb"
        if line in {"fast_vwap", "slow_vwap", "vwap_color"}:
            return "hck"
        for prefix, tool_key in (
            ("sma_", "sma"),
            ("ema_", "ema"),
            ("tema_", "tema"),
            ("hma_", "hma"),
            ("kama_", "kama"),
        ):
            if line.startswith(prefix):
                return tool_key
    return ""


def _infer_tool_key_from_title(title: str) -> str:
    normalized = _normalize_tool_key(title)
    if normalized in _KNOWN_TOOL_KEYS:
        return normalized
    if "peaks" in normalized and "troughs" in normalized:
        return "peaks_troughs"
    if "universal" in normalized and "trend" in normalized:
        return "universal_trend_classifier"
    if "strategy" in normalized:
        return "strategy"
    if "bollinger" in normalized:
        return "bb"
    return ""


def _compact_study_label(
    tool_key: str,
    *,
    title: str,
    line_keys: Sequence[str],
) -> str:
    normalized_tool = _normalize_tool_key(tool_key)
    if normalized_tool == "sma":
        return _label_with_period("S", "sma_", line_keys)
    if normalized_tool == "ema":
        return _label_with_period("E", "ema_", line_keys)
    if normalized_tool == "tema":
        return _label_with_period("TEMA", "tema_", line_keys)
    if normalized_tool == "hma":
        return _label_with_period("HMA", "hma_", line_keys)
    if normalized_tool in _POLICY_LABELS:
        return _POLICY_LABELS[normalized_tool]
    fallback = str(title or "").strip()
    if fallback:
        return fallback
    first_line_key = next((key for key in line_keys if key), "")
    return first_line_key or "Study"


def _label_with_period(prefix: str, line_prefix: str, line_keys: Sequence[str]) -> str:
    period = _first_period_for_prefix(line_prefix, line_keys)
    return f"{prefix}{period}" if period else prefix


def _first_period_for_prefix(line_prefix: str, line_keys: Sequence[str]) -> str:
    pattern = re.compile(rf"^{re.escape(line_prefix)}(\d+)(?:_|$)")
    for line_key in line_keys:
        match = pattern.match(str(line_key or "").strip())
        if match:
            return match.group(1)
    return ""


def _strategy_signal_label(line_key: str) -> str:
    match = re.match(r"^st_ema_(\d+)$", line_key)
    if match:
        return f"E{match.group(1)}"
    match = re.match(r"^st_sma_(\d+)$", line_key)
    if match:
        return f"S{match.group(1)}"
    return ""


def _fallback_signal_label(line_key: str) -> str:
    tokens = [token for token in re.split(r"_+", str(line_key or "").strip()) if token]
    if not tokens:
        return "Value"
    label_parts: list[str] = []
    for token in tokens[:3]:
        label_parts.append(token if token.isdigit() else token[0].upper())
    return "".join(label_parts) or "Value"
