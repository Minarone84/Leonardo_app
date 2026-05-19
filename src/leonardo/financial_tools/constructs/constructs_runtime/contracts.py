from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import pandas as pd

from leonardo.financial_tools.execution_context import ToolExecutionContext


@dataclass(frozen=True)
class ConstructRequest:
    name: str
    data: pd.DataFrame
    params: Dict[str, Any] = field(default_factory=dict)
    context: ToolExecutionContext = field(default_factory=ToolExecutionContext)


@dataclass(frozen=True)
class ConstructLine:
    key: str
    title: str
    values: pd.Series


@dataclass(frozen=True)
class ConstructResult:
    name: str
    title: str
    index: pd.Index
    time: pd.Series
    timeframe: pd.Series
    params: Dict[str, Any]
    lines: tuple[ConstructLine, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)
