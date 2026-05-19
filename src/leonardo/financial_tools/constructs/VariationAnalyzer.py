from __future__ import annotations

from pathlib import Path
from typing import Union
import json

import numpy as np
import pandas as pd


class VariationAnalyzer:
    r"""
    VariationAnalyzer
    =================
    Estimate a per-series *minimum meaningful step* for one or more numeric time series.

    This class is intentionally narrow in scope. It does **not** bin, classify, label,
    plot, or infer state transitions. Its single responsibility is to inspect the
    *magnitude of movement* in each numeric series and emit a strictly-positive suggested
    step size that can later be used by a downstream discretizer or binning engine.

    Core idea
    ---------
    Let :math:`x_t` be a numeric series and :math:`\Delta_t = x_t - x_{t-1}` its first
    difference. The estimator is built around the absolute movement magnitude
    :math:`|\Delta_t|`.

    For each input series, the algorithm is:

    1. Coerce the series to numeric, drop NaNs, and work on the cleaned series only.
    2. Compute first differences :math:`\Delta` and then :math:`|\Delta|`.
    3. Estimate a *small-but-typical* movement floor.

       - If the series is short, meaning ``len(Δ) <= window``, use a low quantile of
         raw :math:`|\Delta|`.
       - If the series is longer, compute ``rolling(window).mean()`` over
         :math:`|\Delta|`, then take the same low quantile of that rolling mean.

       The long-series path dampens local noise and targets the left tail of typical
       movement rather than isolated micro-moves.

    4. Apply optional per-series clamps to the estimated *floor*.
    5. Multiply the clamped floor by ``multiplier`` to produce ``suggest_step``.
    6. Guarantee that the final emitted step is strictly positive, even for flat or
       pathological inputs, by falling back to ``max(per_series_min, global_min_step)``
       when needed.

    Why this estimator exists
    -------------------------
    Many downstream analysis pipelines need a stable minimum movement scale before they
    can partition values into bins or state labels. Using the raw minimum move is too
    fragile, while using a central tendency of all movement magnitudes is often too wide.

    This estimator deliberately aims for a conservative floor:

    - it is based on *movement* rather than raw level distribution,
    - it focuses on a *low quantile* rather than the median or mean,
    - it can be constrained with explicit per-series bounds,
    - and it never emits a zero or negative step.

    Scope boundary
    --------------
    This class estimates *scale*, nothing more.

    It does **not**:
    - align series against each other,
    - preserve a joint index across series,
    - infer categories or labels,
    - define bin edges,
    - decide positive/negative state semantics,
    - or decide how the result should later be rendered or persisted in a larger system.

    In other words, this is a foundational analysis utility, not a chart study.

    Parameters
    ----------
    data : dict[str, pandas.Series] | pandas.DataFrame
        Input series to analyze. If a DataFrame is provided, each column is treated as an
        independent series. Values are coerced to numeric; non-numeric entries become NaN
        and are dropped. Each series is analyzed independently after cleaning.
    window : int, default 50
        Rolling window length used by the long-series estimator. Must be an integer >= 2.
        The rolling-path estimator is used only when ``len(Δ) > window``.
    multiplier : float, default 1.0
        Final multiplicative factor applied **after** the movement floor has been
        estimated and clamped. Values > 1 widen the final step. Values between 0 and 1
        tighten it. Must be strictly positive.
    floor_quantile : float, default 0.05
        Quantile in ``[0, 1]`` used to estimate the lower movement floor. Lower values
        make the floor more aggressive. Higher values make it more conservative.
    per_series_min : dict[str, float], optional
        Per-series hard lower bound for the *estimated floor* **before** the multiplier is
        applied. Values must be non-negative. Unknown series keys raise. When both
        ``per_series_min`` and ``per_series_max`` are provided for the same series, the
        minimum must not exceed the maximum.
    per_series_max : dict[str, float], optional
        Per-series hard upper bound for the *estimated floor* **before** the multiplier is
        applied. Values must be non-negative. Unknown series keys raise. When both
        ``per_series_min`` and ``per_series_max`` are provided for the same series, the
        maximum must not be below the minimum.
    global_min_step : float, default 1e-12
        Global strictly-positive fallback floor for the final emitted step. This exists to
        protect downstream consumers from zero / NaN / negative output on flat or invalid
        inputs. Must be non-negative.
    quantile_method : {"nearest", "lower", "higher", "midpoint", "linear"}, default "nearest"
        Quantile algorithm passed to pandas. Newer pandas versions accept ``method=`` and
        older versions accept ``interpolation=``. This parameter is validated explicitly
        so invalid configurations fail early and locally.

    Attributes
    ----------
    series_dict : dict[str, pandas.Series]
        Cleaned numeric series after coercion and NaN removal, keyed by series name.
    table : pandas.DataFrame | None
        Diagnostic table populated by :meth:`fit`. Indexed by series name. Contains
        summary statistics over first differences, absolute-difference diagnostics, the
        estimated floor, and the final ``suggest_step``.
    steps : dict[str, float] | None
        Mapping ``{series_name: suggest_step}`` populated by :meth:`fit`.

    Notes
    -----
    - The estimator works on first differences, so the meaning of the emitted step is
      tied to the sampling frequency and preprocessing of the input series.
    - ``per_series_min`` and ``per_series_max`` constrain ``floor_mean`` before the
      multiplier is applied. They do **not** directly constrain the final
      ``suggest_step``.
    - ``std`` is intentionally reported as NaN when undefined (for ``n <= 1``) rather
      than forcing a misleading zero.
    - If a cleaned series has fewer than two usable values, then ``Δ`` is empty, the
      estimated floor is undefined, and the final step falls back to the strictly-positive
      safety path.

    Examples
    --------
    >>> va = VariationAnalyzer(
    ...     df[["A", "B"]],
    ...     window=50,
    ...     floor_quantile=0.05,
    ...     multiplier=1.0,
    ... )
    >>> va.fit()
    >>> va.table.loc["A", ["floor_mean", "suggest_step"]]
    >>> va.steps["A"]
    >>> va.save_steps("min_steps.json", overwrite=True)
    """

    _ALLOWED_QUANTILE_METHODS = {"nearest", "lower", "higher", "midpoint", "linear"}

    def __init__(
        self,
        data: Union[dict[str, pd.Series], pd.DataFrame],
        *,
        window: int = 50,
        multiplier: float = 1.0,
        floor_quantile: float = 0.05,
        per_series_min: dict[str, float] | None = None,
        per_series_max: dict[str, float] | None = None,
        global_min_step: float = 1e-12,
        quantile_method: str = "nearest",
    ):
        # Normalize the incoming container into a dict[str, Series].
        #
        # This utility is deliberately per-series and does not require cross-series
        # alignment, so we keep the normalization simple and preserve each series as an
        # independent object.
        if isinstance(data, pd.DataFrame):
            data = {col: data[col] for col in data.columns}
        if not isinstance(data, dict):
            raise TypeError("data must be a dict[str, Series] or a DataFrame")

        # Validate the global estimator configuration up front so failures happen early,
        # close to the call site, rather than deep inside pandas or numeric operations.
        if not isinstance(window, int) or window < 2:
            raise ValueError("window must be an integer >= 2")
        if not (0.0 <= float(floor_quantile) <= 1.0):
            raise ValueError("floor_quantile must be within [0, 1]")
        if float(multiplier) <= 0:
            raise ValueError("multiplier must be > 0")
        if float(global_min_step) < 0:
            raise ValueError("global_min_step must be >= 0")
        if quantile_method not in self._ALLOWED_QUANTILE_METHODS:
            raise ValueError(
                "quantile_method must be one of "
                f"{sorted(self._ALLOWED_QUANTILE_METHODS)}"
            )

        if per_series_min and any(float(v) < 0 for v in per_series_min.values()):
            raise ValueError("per_series_min must be non-negative")
        if per_series_max and any(float(v) < 0 for v in per_series_max.values()):
            raise ValueError("per_series_max must be non-negative")

        # Perform numeric coercion once, drop NaNs once, and retain only usable series.
        #
        # Empty post-cleaning series are discarded because they provide no signal for
        # variation analysis. If everything disappears after cleaning, that is a real
        # configuration/data problem and should fail loudly.
        cleaned: dict[str, pd.Series] = {}
        for k, v in data.items():
            s = pd.to_numeric(v, errors="coerce").dropna().astype(float)
            if not s.empty:
                cleaned[k] = s
        if not cleaned:
            raise ValueError("no non-empty numeric series found")

        self.series_dict = cleaned
        self.window = window
        self.multiplier = float(multiplier)
        self.floor_quantile = float(floor_quantile)
        self.per_series_min = per_series_min or {}
        self.per_series_max = per_series_max or {}
        self.global_min_step = float(global_min_step)
        self.quantile_method = quantile_method

        # Disallow clamp configuration for unknown series names.
        #
        # Silent acceptance of typoed series keys would make the estimator look valid
        # while quietly ignoring user intent.
        unknown_min = set(self.per_series_min) - set(self.series_dict)
        unknown_max = set(self.per_series_max) - set(self.series_dict)
        if unknown_min:
            raise ValueError(f"Unknown per_series_min keys: {unknown_min}")
        if unknown_max:
            raise ValueError(f"Unknown per_series_max keys: {unknown_max}")

        # If both bounds are present for a series, validate the relationship explicitly.
        #
        # Sequentially applying contradictory bounds would be deterministic but misleading.
        # The caller should be told immediately when the configuration is internally
        # inconsistent.
        overlapping_bounds = set(self.per_series_min) & set(self.per_series_max)
        for name in sorted(overlapping_bounds):
            lo = float(self.per_series_min[name])
            hi = float(self.per_series_max[name])
            if lo > hi:
                raise ValueError(
                    f"per_series_min[{name!r}] ({lo}) cannot exceed "
                    f"per_series_max[{name!r}] ({hi})"
                )

        self.table: pd.DataFrame | None = None
        self.steps: dict[str, float] | None = None

    def _q(self, s: pd.Series, q: float):
        """
        Return a quantile using the configured quantile algorithm.

        pandas changed this API over time: newer versions use ``method=`` while older
        versions use ``interpolation=``. This helper keeps the estimator logic readable
        and keeps compatibility concerns in one place.
        """
        try:
            return s.quantile(q, method=self.quantile_method)
        except TypeError:
            return s.quantile(q, interpolation=self.quantile_method)

    def fit(self):
        """
        Estimate ``suggest_step`` for every cleaned input series.

        For each series:
        1. compute first differences ``Δ`` and ``|Δ|``;
        2. choose the short-series or long-series floor estimator;
        3. apply per-series floor clamps, if configured;
        4. multiply by ``multiplier``;
        5. guarantee a strictly-positive final value for downstream safety;
        6. collect a diagnostic row describing what happened.

        Returns
        -------
        VariationAnalyzer
            The fitted instance, allowing fluent usage such as
            ``VariationAnalyzer(...).fit()``.
        """
        rows: list[dict[str, float | str]] = []

        for name, series in self.series_dict.items():
            d = series.diff().dropna()
            abs_d = d.abs()
            n = len(d)

            # Estimate the movement floor according to the documented regime split.
            #
            # Short series use the low quantile of raw |Δ| directly because introducing a
            # rolling mean there would reduce the already-limited sample and can bias the
            # result upward. Longer series can afford the rolling-mean path, which yields a
            # more stable estimate of the lower tail of typical movement.
            if n == 0:
                floor_mean = np.nan
            elif n <= self.window:
                floor_mean = self._q(abs_d, self.floor_quantile)
            else:
                roll = abs_d.rolling(self.window).mean().dropna()
                floor_mean = self._q(roll, self.floor_quantile)

            # Clamp the estimated floor, not the final multiplied step.
            if name in self.per_series_min and pd.notna(floor_mean):
                floor_mean = max(float(floor_mean), float(self.per_series_min[name]))
            if name in self.per_series_max and pd.notna(floor_mean):
                floor_mean = min(float(floor_mean), float(self.per_series_max[name]))

            # Compute the final emitted step. If the estimate is unusable, fall through to
            # the safety path below.
            suggest_step = (
                float(floor_mean) * self.multiplier if pd.notna(floor_mean) else np.nan
            )

            # Downstream binners require a strictly-positive scale. Whenever the estimated
            # step is NaN, infinite, or non-positive, emit the strongest available safety
            # lower bound instead of silently propagating an invalid value.
            if (not np.isfinite(suggest_step)) or (suggest_step <= 0):
                suggest_step = max(
                    float(self.per_series_min.get(name, 0.0)),
                    self.global_min_step,
                )

            rows.append(
                {
                    "series": name,
                    "count": n,
                    "mean": float(d.mean()) if n else np.nan,
                    "std": float(d.std(ddof=1)) if n > 1 else np.nan,
                    "min": float(d.min()) if n else np.nan,
                    "max": float(d.max()) if n else np.nan,
                    "abs_mean": float(abs_d.mean()) if n else np.nan,
                    "abs_median": float(abs_d.median()) if n else np.nan,
                    "pctile_95": float(self._q(d, 0.95)) if n else np.nan,
                    "pctile_99": float(self._q(d, 0.99)) if n else np.nan,
                    "abs_pctile_95": float(self._q(abs_d, 0.95)) if n else np.nan,
                    "abs_pctile_99": float(self._q(abs_d, 0.99)) if n else np.nan,
                    "floor_quantile": self.floor_quantile,
                    "floor_mean": float(floor_mean) if pd.notna(floor_mean) else np.nan,
                    "suggest_step": float(suggest_step),
                }
            )

        self.table = pd.DataFrame(rows).set_index("series")
        self.steps = {
            idx: float(row["suggest_step"])
            for idx, row in self.table.iterrows()
        }
        return self

    def save_steps(self, filepath: str | Path, *, overwrite: bool = False) -> Path:
        """
        Persist the fitted ``{series_name: suggest_step}`` mapping as JSON.

        This method intentionally writes only the final step mapping. It does not persist
        the full diagnostic table because artifact-management policy belongs at a higher
        integration layer.

        Parameters
        ----------
        filepath : str | pathlib.Path
            Destination JSON file path.
        overwrite : bool, default False
            If ``False`` and the destination already exists, raise ``FileExistsError``.

        Returns
        -------
        pathlib.Path
            The normalized destination path actually written.
        """
        if self.steps is None:
            raise RuntimeError("call .fit() first")

        path = Path(filepath)
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} exists (set overwrite=True to replace)")

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump({k: float(v) for k, v in self.steps.items()}, f, indent=2)

        return path