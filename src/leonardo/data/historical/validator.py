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
    code: str | None = None
    row_index: int | None = None
    ts_ms: int | None = None
    column: str | None = None
    repairable: bool | None = None


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
                issues=[
                    ValidationIssue(
                        "error",
                        "file does not exist",
                        code="file_missing",
                        repairable=False,
                    )
                ],
                row_count=0,
            )

        rows = []
        with file_path.open("r", newline="") as f:
            reader = csv.DictReader(f)

            # ---- schema check ----
            if reader.fieldnames is None:
                return ValidationReport(
                    status="error",
                    issues=[
                        ValidationIssue(
                            "error",
                            "missing CSV header",
                            code="missing_csv_header",
                            repairable=False,
                        )
                    ],
                    row_count=0,
                )

            for col in self.REQUIRED_COLUMNS:
                if col not in reader.fieldnames:
                    return ValidationReport(
                        status="error",
                        issues=[
                            ValidationIssue(
                                "error",
                                f"missing column: {col}",
                                code="missing_column",
                                column=col,
                                repairable=False,
                            )
                        ],
                        row_count=0,
                    )

            for r in reader:
                rows.append(r)

        if not rows:
            return ValidationReport(
                status="error",
                issues=[
                    ValidationIssue(
                        "error",
                        "empty dataset",
                        code="empty_dataset",
                        repairable=False,
                    )
                ],
                row_count=0,
            )

        prev_ts: Optional[int] = None
        gap_count = 0

        for i, r in enumerate(rows):
            try:
                ts = int(r["ts_ms"])
            except Exception as e:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"parse error at row {i}: {e}",
                        code="parse_error",
                        row_index=i,
                        column="ts_ms",
                        repairable=False,
                    )
                )
                continue

            try:
                o = float(r["open"])
                h = float(r["high"])
                l = float(r["low"])
                c = float(r["close"])
                v = float(r["volume"])
            except Exception as e:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"parse error at row {i}: {e}",
                        code="parse_error",
                        row_index=i,
                        ts_ms=ts,
                        column=self._parse_error_column(r),
                        repairable=None,
                    )
                )
                continue

            # ---- finite checks ----
            finite_values = {
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
            non_finite_columns = [
                column for column, value in finite_values.items() if not math.isfinite(value)
            ]
            if non_finite_columns:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"non-finite values at row {i}",
                        code="non_finite_values",
                        row_index=i,
                        ts_ms=ts,
                        column=non_finite_columns[0] if len(non_finite_columns) == 1 else None,
                        repairable=True,
                    )
                )
                continue

            # ---- OHLC checks ----
            if not (l <= h):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"low > high at row {i}",
                        code="low_greater_than_high",
                        row_index=i,
                        ts_ms=ts,
                        repairable=True,
                    )
                )

            if not (l <= o <= h):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"open out of bounds at row {i}",
                        code="open_out_of_bounds",
                        row_index=i,
                        ts_ms=ts,
                        column="open",
                        repairable=True,
                    )
                )

            if not (l <= c <= h):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"close out of bounds at row {i}",
                        code="close_out_of_bounds",
                        row_index=i,
                        ts_ms=ts,
                        column="close",
                        repairable=True,
                    )
                )

            if v < 0:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"negative volume at row {i}",
                        code="negative_volume",
                        row_index=i,
                        ts_ms=ts,
                        column="volume",
                        repairable=True,
                    )
                )

            # ---- timestamp checks ----
            if prev_ts is not None:
                if ts <= prev_ts:
                    issues.append(
                        ValidationIssue(
                            "error",
                            f"non-increasing timestamp at row {i}",
                            code="non_increasing_timestamp",
                            row_index=i,
                            ts_ms=ts,
                            column="ts_ms",
                            repairable=True,
                        )
                    )

                if not self._skip_exact_delta_check:
                    delta = ts - prev_ts
                    if delta != self.step_ms:
                        gap_count += 1

            prev_ts = ts

        if gap_count > 0:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"{gap_count} timeframe gaps detected",
                    code="gap_count",
                    repairable=True,
                )
            )

        if self._skip_exact_delta_check:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"exact timeframe continuity check skipped for variable-length timeframe: {self.timeframe}",
                    code="variable_timeframe_continuity_skipped",
                    repairable=False,
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

    def _parse_error_column(self, row: dict[str, str]) -> str | None:
        for column in ("open", "high", "low", "close", "volume"):
            try:
                float(row[column])
            except Exception:
                return column
        return None
