from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List

@dataclass(frozen=True)
class Candle:
    o: float
    h: float
    l: float
    c: float

def make_dummy_candles(n: int = 220, seed: int = 7) -> List[Candle]:
    rng = random.Random(seed)
    price = 100.0
    out: List[Candle] = []
    for _ in range(n):
        o = price
        delta = rng.uniform(-1.5, 1.5)
        c = max(1.0, o + delta)
        hi = max(o, c) + rng.uniform(0.1, 1.2)
        lo = min(o, c) - rng.uniform(0.1, 1.2)
        lo = max(0.5, lo)
        out.append(Candle(o=o, h=hi, l=lo, c=c))
        price = c
    return out

def make_dummy_volume(n: int = 220, seed: int = 11) -> List[float]:
    rng = random.Random(seed)
    base = 1000.0
    out: List[float] = []
    for i in range(n):
        v = base + 350.0 * math.sin(i * 0.12) + rng.uniform(-180, 180)
        out.append(max(50.0, v))
    return out

def make_dummy_oscillator(n: int = 220, seed: int = 13) -> List[float]:
    rng = random.Random(seed)
    out: List[float] = []
    x = 50.0
    for i in range(n):
        x += 3.0 * math.sin(i * 0.08) + rng.uniform(-2.0, 2.0)
        x = max(0.0, min(100.0, x))
        out.append(x)
    return out

def make_default_oscillators(n: int = 220) -> Dict[str, List[float]]:
    return {
        "rsi_14": make_dummy_oscillator(n=n, seed=13),
        "macd_12_26_9": make_dummy_oscillator(n=n, seed=17),
    }
