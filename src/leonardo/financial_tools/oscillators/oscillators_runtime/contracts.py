from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

import pandas as pd

from leonardo.financial_tools.execution_context import ToolExecutionContext


@dataclass(frozen=True)
class OscillatorRequest:
    """
    Normalized request contract for oscillator computation.

    Attributes:
        name: Oscillator name, e.g. 'rsi'
        data: Input dataframe
        params: Oscillator parameters
    """
    name: str
    data: pd.DataFrame
    params: Mapping[str, Any]
    context: ToolExecutionContext = field(default_factory=ToolExecutionContext)


@dataclass(frozen=True)
class OscillatorLine:
    """
    One plot-ready output line from an oscillator.
    """
    key: str
    title: str
    values: pd.Series


@dataclass(frozen=True)
class OscillatorResult:
    """
    Normalized result contract for oscillator computation.

    Attributes:
        name: Internal oscillator name
        title: Human-readable title
        kind: Oscillator classification
        lines: Output line(s)
        index: Output index, preserved from input
        time: Output time column
        timeframe: Output timeframe column
        params: Effective validated params
    """
    name: str
    title: str
    kind: str
    lines: List[OscillatorLine]
    index: pd.Index
    time: pd.Series | None
    timeframe: pd.Series | None
    params: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
