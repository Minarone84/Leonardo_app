from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from leonardo.data.naming import normalize_timeframe


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    message: str


@dataclass
class ValidationReport:
    status: str  # "ok" | "warning" | "error"
    issues: List[ValidationIssue]
    row_count: int


class HistoricalDatasetValidator:
    REQUIRED_COLUMNS = ["ts_ms", "open", "high", "low", "close", "volume"]

    def __init__(self, timeframe: str):
        self.timeframe = timeframe
        self.step_ms = self._tf_to_ms(timeframe)
        self._skip_exact_delta_check = self.step_ms is None

    def validate(self, file_path: Path) -> ValidationReport:
        issues: List[ValidationIssue] = []

        if not file_path.exists():
            return ValidationReport(
                status="error",
                issues=[ValidationIssue("error", "file does not exist")],
                row_count=0,
            )

        rows = []
        with file_path.open("r", newline="") as f:
            reader = csv.DictReader(f)

            # ---- schema check ----
            if reader.fieldnames is None:
                return ValidationReport(
                    status="error",
                    issues=[ValidationIssue("error", "missing CSV header")],
                    row_count=0,
                )

            for col in self.REQUIRED_COLUMNS:
                if col not in reader.fieldnames:
                    return ValidationReport(
                        status="error",
                        issues=[ValidationIssue("error", f"missing column: {col}")],
                        row_count=0,
                    )

            for r in reader:
                rows.append(r)

        if not rows:
            return ValidationReport(
                status="error",
                issues=[ValidationIssue("error", "empty dataset")],
                row_count=0,
            )

        prev_ts: Optional[int] = None
        gap_count = 0

        for i, r in enumerate(rows):
            try:
                ts = int(r["ts_ms"])

                o = float(r["open"])
                h = float(r["high"])
                l = float(r["low"])
                c = float(r["close"])
                v = float(r["volume"])

                # ---- finite checks ----
                if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                    issues.append(ValidationIssue("error", f"non-finite values at row {i}"))
                    continue

                # ---- OHLC checks ----
                if not (l <= h):
                    issues.append(ValidationIssue("error", f"low > high at row {i}"))

                if not (l <= o <= h):
                    issues.append(ValidationIssue("error", f"open out of bounds at row {i}"))

                if not (l <= c <= h):
                    issues.append(ValidationIssue("error", f"close out of bounds at row {i}"))

                if v < 0:
                    issues.append(ValidationIssue("error", f"negative volume at row {i}"))

                # ---- timestamp checks ----
                if prev_ts is not None:
                    if ts <= prev_ts:
                        issues.append(ValidationIssue("error", f"non-increasing timestamp at row {i}"))

                    if not self._skip_exact_delta_check:
                        delta = ts - prev_ts
                        if delta != self.step_ms:
                            gap_count += 1

                prev_ts = ts

            except Exception as e:
                issues.append(ValidationIssue("error", f"parse error at row {i}: {e}"))

        if gap_count > 0:
            issues.append(ValidationIssue("warning", f"{gap_count} timeframe gaps detected"))

        if self._skip_exact_delta_check:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"exact timeframe continuity check skipped for variable-length timeframe: {self.timeframe}",
                )
            )

        # ---- status resolution ----
        status = "ok"
        if any(i.severity == "error" for i in issues):
            status = "error"
        elif issues:
            status = "warning"

        return ValidationReport(
            status=status,
            issues=issues,
            row_count=len(rows),
        )

    def _tf_to_ms(self, tf: str) -> Optional[int]:
        """Return fixed-duration milliseconds for neutral Option A timeframes.

        The validator must not carry an exchange-specific supported-timeframe
        table. It only needs to know whether a canonical timeframe has a fixed
        duration so it can check timestamp continuity. Variable-length month
        candles skip the exact-delta check.
        """
        canonical = normalize_timeframe(tf)
        unit = canonical[-1]
        value = int(canonical[:-1])
        if value <= 0:
            raise ValueError(f"unsupported timeframe: {tf}")

        if unit == "m":
            return value * 60_000
        if unit == "h":
            return value * 3_600_000
        if unit == "d":
            return value * 86_400_000
        if unit == "w":
            return value * 7 * 86_400_000
        if unit == "M":
            return None

        raise ValueError(f"unsupported timeframe: {tf}")