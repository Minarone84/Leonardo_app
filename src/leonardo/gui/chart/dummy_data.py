from __future__ import annotations

import math
import random
import time
from typing import Dict, Iterator, List, Optional

from leonardo.common.market_types import Candle


def make_dummy_candles(n: int = 220, seed: int = 7, start_ts_ms: Optional[int] = None, step_ms: int = 60_000) -> List[Candle]:
    """
    Generates a deterministic candle series with timestamps.
    """
    rng = random.Random(seed)
    price = 100.0
    out: List[Candle] = []

    if start_ts_ms is None:
        # Align to "now - n minutes"
        now_ms = int(time.time() * 1000)
        start_ts_ms = now_ms - (n * step_ms)

    ts = start_ts_ms
    for _ in range(n):
        o = price
        delta = rng.uniform(-1.5, 1.5)
        c = max(1.0, o + delta)
        hi = max(o, c) + rng.uniform(0.1, 1.2)
        lo = min(o, c) - rng.uniform(0.1, 1.2)
        lo = max(0.5, lo)

        out.append(Candle(
            ts_ms=ts,
            open=float(o),
            high=float(hi),
            low=float(lo),
            close=float(c),
            volume=float(max(50.0, 1000.0 + rng.uniform(-250.0, 250.0))),
            is_closed=True,
        ))

        price = c
        ts += step_ms

    return out


def make_dummy_volume(n: int = 220, seed: int = 11) -> List[float]:
    """
    Kept for compatibility; workspace now derives volume from candles during snapshot.
    """
    rng = random.Random(seed)
    base = 1000.0
    out: List[float] = []
    for i in range(n):
        v = base + 350.0 * math.sin(i * 0.12) + rng.uniform(-180, 180)
        out.append(max(50.0, float(v)))
    return out


def make_dummy_oscillator(n: int = 220, seed: int = 13) -> List[float]:
    rng = random.Random(seed)
    out: List[float] = []
    x = 50.0
    for i in range(n):
        x += 3.0 * math.sin(i * 0.08) + rng.uniform(-2.0, 2.0)
        x = max(0.0, min(100.0, x))
        out.append(float(x))
    return out


def make_default_oscillators(n: int = 220) -> Dict[str, List[float]]:
    return {
        "rsi_14": make_dummy_oscillator(n=n, seed=13),
        "macd_12_26_9": make_dummy_oscillator(n=n, seed=17),
    }


# -------------------------------------------------------
# Realtime dummy data (for testing chart patch pipeline)
# -------------------------------------------------------

def iter_dummy_realtime_patches(
    *,
    last_candle: Candle,
    seed: int = 42,
    updates_per_candle: int = 6,
    step_ms: int = 60_000,
) -> Iterator[tuple[str, Candle]]:
    """
    Yields ("update" | "append", Candle) indefinitely.

    Semantics:
    - emits several "update" events (open candle evolving)
    - then emits one "append" (closing the candle and starting a new one)

    This is purely for testing the GUI apply_patch pipeline before real exchanges.
    """
    rng = random.Random(seed)

    cur = Candle(
        ts_ms=last_candle.ts_ms + step_ms,
        open=last_candle.close,
        high=last_candle.close,
        low=last_candle.close,
        close=last_candle.close,
        volume=0.0,
        is_closed=False,
    )

    while True:
        # several updates within the candle
        for _ in range(max(1, updates_per_candle)):
            delta = rng.uniform(-0.8, 0.8)
            new_close = max(0.5, cur.close + delta)

            new_high = max(cur.high, new_close)
            new_low = min(cur.low, new_close)
            new_vol = max(0.0, cur.volume + rng.uniform(20.0, 160.0))

            cur = Candle(
                ts_ms=cur.ts_ms,
                open=cur.open,
                high=new_high,
                low=new_low,
                close=new_close,
                volume=new_vol,
                is_closed=False,
            )
            yield ("update", cur)

        # close candle & append it
        closed = Candle(
            ts_ms=cur.ts_ms,
            open=cur.open,
            high=cur.high,
            low=cur.low,
            close=cur.close,
            volume=cur.volume,
            is_closed=True,
        )
        yield ("append", closed)

        # start next candle
        cur = Candle(
            ts_ms=cur.ts_ms + step_ms,
            open=closed.close,
            high=closed.close,
            low=closed.close,
            close=closed.close,
            volume=0.0,
            is_closed=False,
        )