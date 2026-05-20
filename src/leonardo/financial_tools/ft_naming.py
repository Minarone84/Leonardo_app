from __future__ import annotations

"""Public naming façade for Leonardo financial tools.

This module intentionally preserves the historical public import surface.
Implementation is split under ``naming_runtime`` by responsibility:
tokens, hashing, indicator naming, oscillator naming, construct naming,
binding slugs, and persistence/file identity.
"""

from .naming_runtime.tokens import _slugify_token, build_source_token
from .naming_runtime.hashing import _normalize_param_value, _json_signature, _short_hash
from .naming_runtime.constructs_core import (
    _normalize_construct_key,
    _normalize_construct_source,
    _normalize_construct_sources,
    _normalize_fast_slow_pair,
    _resolve_delta_pairs_from_params,
)
from .naming_runtime.indicators import (
    STRATEGY_EMA_SLOT_COUNT,
    STRATEGY_SMA_SLOT_COUNT,
    PEAKS_TROUGHS_FRACTAL_LENGTHS,
    build_indicator_signal_name,
    build_sma_signal_name,
    build_ema_signal_name,
    build_tema_signal_name,
    build_hma_signal_name,
    build_kama_signal_name,
    build_bb_signal_names,
    build_hck_signal_names,
    _validate_strategy_slot,
    build_strategy_ema_signal_name,
    build_strategy_sma_signal_name,
    build_strategy_bb_signal_names,
    build_strategy_hck_signal_names,
    build_strategy_signal_names,
    build_peaks_troughs_signal_name,
    build_peaks_troughs_signal_names,
    UNIVERSAL_TREND_CLASSIFIER_SIGNAL_NAMES,
    build_universal_trend_classifier_signal_names,
    get_indicator_signal_names,
)
from .naming_runtime.oscillators import (
    build_oscillator_signal_name,
    build_rsi_signal_name,
    build_arsi_signal_name,
    build_arsi_signal_names,
    build_tdirsi_signal_names,
    build_smi_signal_names,
    build_mfi_signal_name,
    build_obv_signal_name,
    build_volume_signal_names,
    get_oscillator_signal_names,
)
from .naming_runtime.constructs import (
    build_unary_name,
    build_delta_name,
    build_fms_prefix,
    build_fms_name,
    build_derivative_signal_names,
    build_angle_signal_name,
    build_braids_signal_names,
    build_braid_instability_signal_name,
    build_delta_signal_name,
    build_trap_area_signal_names,
    build_percent_span_angle_signal_name,
    build_angle_momentum_signal_name,
    _resolve_percent_span_angle_windows_from_params,
    get_construct_signal_names,
)
from .naming_runtime.bindings import (
    build_src_binding_slug,
    build_sources_binding_slug,
    build_left_right_binding_slug,
    build_source_reference_binding_slug,
    build_fms_binding_slug,
    build_fs_binding_slug,
    build_binding_slug_from_params,
)
from .naming_runtime.persistence import (
    build_construct_instance_key_from_params,
    resolve_construct_token,
    _is_unary_single_source_construct,
    build_param_slug,
    build_construct_instance_key,
    build_construct_filename,
)
from .naming_runtime.registry import get_tool_signal_names

