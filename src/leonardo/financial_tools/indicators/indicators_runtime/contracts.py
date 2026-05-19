from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

import pandas as pd

from leonardo.financial_tools.execution_context import ToolExecutionContext


@dataclass(frozen=True)
class IndicatorRequest:
    """
    Normalized request contract for indicator computation.

    Attributes:
        name: Indicator name, e.g. 'sma'
        data: Input dataframe
        params: Indicator parameters
    """

    name: str
    data: pd.DataFrame
    params: Mapping[str, Any]
    context: ToolExecutionContext = field(default_factory=ToolExecutionContext)


@dataclass(frozen=True)
class IndicatorLine:
    """
    One plot-ready output line from an indicator.
    """

    key: str
    title: str
    values: pd.Series


@dataclass(frozen=True)
class IndicatorResult:
    """
    Normalized result contract for indicator computation.

    Attributes:
        name: Internal indicator name, e.g. 'sma'
        title: Human-readable title
        kind: Overlay classification
        lines: Output line(s)
        index: Output index, preserved from input
        time: Output time column
        timeframe: Output timeframe column
        params: Effective validated params
    """

    name: str
    title: str
    kind: str
    lines: List[IndicatorLine]
    index: pd.Index
    time: pd.Series | None
    timeframe: pd.Series | None
    params: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
