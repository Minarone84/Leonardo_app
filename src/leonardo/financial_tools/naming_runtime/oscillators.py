from __future__ import annotations

from typing import Any

from .tokens import _slugify_token

def build_oscillator_signal_name(oscillator_key: str, *parts: Any) -> str:
    """
    Build a canonical lowercase signal name for parameterized single-output
    oscillators.
    """
    base = _slugify_token(oscillator_key)
    suffix_parts = [_slugify_token(part) for part in parts if part is not None and str(part) != ""]
    if not suffix_parts:
        return base
    return "_".join([base, *suffix_parts])


def build_rsi_signal_name(period: Any) -> str:
    return build_oscillator_signal_name("rsi", period)


def build_arsi_signal_name(period: Any) -> str:
    return build_oscillator_signal_name("arsi", period)


def build_arsi_signal_names(
    period: Any,
    method: Any,
    signal_period: Any,
    signal_method: Any,
) -> tuple[str, str]:
    """
    Canonical Ultimate RSI-style ARSI output names.
    """
    return (
        build_oscillator_signal_name("arsi", period, method),
        build_oscillator_signal_name("arsi_signal", period, method, signal_period, signal_method),
    )


def build_tdirsi_signal_names(
    period: Any,
    band_length: Any,
    fast_len: Any,
    slow_len: Any,
    fast_smo: Any,
    slow_smo: Any,
) -> tuple[str, str, str, str, str]:
    """
    Canonical TDI RSI output names.
    """
    suffix = (
        _slugify_token(period),
        _slugify_token(band_length),
        _slugify_token(fast_len),
        _slugify_token(slow_len),
        _slugify_token(fast_smo),
        _slugify_token(slow_smo),
    )

    return (
        build_oscillator_signal_name("tdirsi_fast_ma", *suffix),
        build_oscillator_signal_name("tdirsi_slow_ma", *suffix),
        build_oscillator_signal_name("tdirsi_up", *suffix),
        build_oscillator_signal_name("tdirsi_dn", *suffix),
        build_oscillator_signal_name("tdirsi_mid", *suffix),
    )


def build_smi_signal_names(k_length: Any, d_length: Any) -> tuple[str, str]:
    """
    Canonical SMI output names.
    """
    return (
        build_oscillator_signal_name("smi", k_length, d_length),
        build_oscillator_signal_name("smi_signal", k_length, d_length),
    )


def build_mfi_signal_name(period: Any) -> str:
    return build_oscillator_signal_name("mfi", period)


def build_obv_signal_name() -> str:
    return "obv"


def build_volume_signal_names(period: Any) -> tuple[str, str]:
    return "volume", build_oscillator_signal_name("volume_mean", period)


def get_oscillator_signal_names(oscillator_key: str, **params: Any) -> tuple[str, ...]:
    """
    Return canonical output signal names for a registered oscillator family.
    """
    key = _slugify_token(oscillator_key)

    if key == "rsi":
        return (build_rsi_signal_name(params["period"]),)

    if key == "arsi":
        return build_arsi_signal_names(
            params.get("period", 14),
            params.get("method", "RMA"),
            params.get("signal_period", 14),
            params.get("signal_method", "EMA"),
        )

    if key == "tdirsi":
        return build_tdirsi_signal_names(
            params["period"],
            params["band_length"],
            params["fast_len"],
            params["slow_len"],
            params["fast_smo"],
            params["slow_smo"],
        )

    if key == "smi":
        return build_smi_signal_names(
            params["k_length"],
            params["d_length"],
        )

    if key == "mfi":
        return (build_mfi_signal_name(params["period"]),)

    if key == "obv":
        return (build_obv_signal_name(),)

    if key == "volume":
        return build_volume_signal_names(params["period"])

    raise KeyError(f"Unsupported oscillator key for canonical signal naming: {oscillator_key}")


# ----------------------------------------------------------------------
# Output column naming helpers
