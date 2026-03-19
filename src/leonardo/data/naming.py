from __future__ import annotations

import re
from dataclasses import dataclass

# ----------------------------
# Option A (Conservative) rules
# ----------------------------
# Exchange:
#   - lowercase, [a-z0-9_]+
# Market type:
#   - strict enum: spot | linear | inverse | options
# Symbol:
#   - uppercase
#   - remove only structural separators: / - _ : space
#   - allow [A-Z0-9.] (dot preserved)
# Timeframe:
#   - <int><unit> with unit in {m,h,d,w,M}
#   - month uses uppercase 'M' (to avoid collision with minutes 'm')
#   - normalize unit aliases (min, hour, day, week, month/mo)
#   - digits-only => minutes (explicit default)
#   - NO auto-conversion (60m stays 60m, 30d stays 30d)

_EXCHANGE_RE = re.compile(r"^[a-z0-9_]+$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9.]+$")

ALLOWED_MARKET_TYPES = {"spot", "linear", "inverse", "options"}

_TIMEFRAME_UNIT_ALIASES = {
    # minutes
    "m": "m",
    "min": "m",
    "mins": "m",
    "minute": "m",
    "minutes": "m",

    # hours
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",

    # days
    "d": "d",
    "day": "d",
    "days": "d",

    # weeks
    "w": "w",
    "wk": "w",
    "wks": "w",
    "week": "w",
    "weeks": "w",

    # months (canonical is uppercase 'M')
    "mo": "M",
    "mon": "M",
    "month": "M",
    "months": "M",
    "mth": "M",
    "mths": "M",
    "mthly": "M",  # tolerate weirdness, still conservative output
    "M": "M",      # allow direct "M" unit if user already uses it
}


@dataclass(frozen=True)
class MarketId:
    """
    Canonical identity of a market dataset.

    This object represents the normalized data identity only:
    - exchange
    - market_type
    - symbol
    - timeframe

    It intentionally does NOT include runtime/session context such as
    'historical' or 'realtime'. That belongs in a higher-level context object.
    """
    exchange: str
    market_type: str
    symbol: str
    timeframe: str


def normalize_exchange(value: str) -> str:
    v = (value or "").strip().lower()

    # alias map (extend as you add venues)
    if v in {"bybit"}:
        v = "bybit"

    if not v or not _EXCHANGE_RE.fullmatch(v):
        raise ValueError(f"invalid exchange: {value!r}")
    return v


def normalize_market_type(value: str) -> str:
    v = (value or "").strip().lower()
    if v not in ALLOWED_MARKET_TYPES:
        raise ValueError(f"invalid market_type: {value!r} (allowed: {sorted(ALLOWED_MARKET_TYPES)})")
    return v


def normalize_symbol(value: str) -> str:
    v = (value or "").strip().upper()

    # remove only structural separators
    for sep in ("/", "-", "_", ":", " "):
        v = v.replace(sep, "")

    if not v or not _SYMBOL_RE.fullmatch(v):
        raise ValueError(f"invalid symbol: {value!r}")
    return v


def normalize_timeframe(value: str) -> str:
    raw0 = (value or "").strip()
    if not raw0:
        raise ValueError("timeframe required")

    # Keep original for month detection; also normalize whitespace
    raw = raw0.strip()

    # digits-only => minutes (explicit policy)
    if raw.isdigit():
        return f"{int(raw)}m"

    # Special-case canonical month like "1M" (uppercase M)
    # We accept "1M" exactly as-is. Anything else gets normalized below.
    if re.fullmatch(r"\d+M", raw):
        n = int(raw[:-1])
        return f"{n}M"

    # For general parsing, normalize to lower for matching unit aliases,
    # but keep ability to resolve month via aliases -> "M".
    raw_l = raw.lower()

    m = re.fullmatch(r"(\d+)\s*([a-zA-Z]+)", raw_l)
    if not m:
        raise ValueError(f"invalid timeframe: {value!r}")

    n = int(m.group(1))
    unit_raw = m.group(2)

    unit = _TIMEFRAME_UNIT_ALIASES.get(unit_raw)
    if unit is None:
        raise ValueError(f"invalid timeframe unit: {unit_raw!r} (expected m/h/d/w/M or aliases)")

    # NO auto-conversion in Option A
    return f"{n}{unit}"


def canonicalize(exchange: str, market_type: str, symbol: str, timeframe: str) -> MarketId:
    """
    Normalize raw market identity components into a canonical MarketId.
    """
    return MarketId(
        exchange=normalize_exchange(exchange),
        market_type=normalize_market_type(market_type),
        symbol=normalize_symbol(symbol),
        timeframe=normalize_timeframe(timeframe),
    )