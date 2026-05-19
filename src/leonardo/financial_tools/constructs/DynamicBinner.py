from __future__ import annotations

from typing import Any, Dict, Union
import math

import numpy as np
import pandas as pd


class DynamicBinner:
    r"""
    DynamicBinner
    =============
    Fit a deterministic signed discretizer for one or more numeric series.

    This class belongs to the *discretization* stage of a larger analytical pipeline.
    It assumes that a strictly-positive per-series minimum meaningful movement step has
    already been estimated upstream, typically by a companion estimator such as
    ``VariationAnalyzer``. In other words, this class does **not** decide what the
    appropriate step size should be. It consumes that decision and builds a stable label
    space around zero.

    Core purpose
    ------------
    For each input series, build exactly:

    - ``n_bins`` positive bins, labeled ``AB0`` .. ``AB{n_bins-1}``
    - ``n_bins`` negative bins, labeled ``BL0`` .. ``BL{n_bins-1}``

    The binning scheme is anchored at zero and fitted independently on the positive and
    negative sides using observed magnitudes plus a minimum-step constraint.

    Why this class exists
    ---------------------
    Many downstream analytical workflows need a *fixed categorical state space* rather
    than raw continuous values. This class converts signed numeric values into a stable,
    ordered, reproducible label system.

    The design goals are:

    - keep the number of bins fixed per side;
    - keep zero as the central pivot;
    - adapt to the observed data distribution using quantiles;
    - enforce a minimum local separation between adjacent bin edges;
    - remain usable even when the requested step is too large for the observed span;
    - preserve enough fitted geometry and metadata to make downstream audit and artifact
      export straightforward rather than mystical.

    Scope boundary
    --------------
    This class is intentionally narrow in scope. It does **not**:

    - estimate ``min_steps``;
    - infer whether a series should be treated as signed or unsigned;
    - render anything;
    - produce charts or visual overlays;
    - orchestrate multi-stage analysis pipelines;
    - decide persistence policy for higher-level constructs.

    It is a fitted signed discretizer, not a general analysis framework.

    Fitted representation
    ---------------------
    After :meth:`fit`, the class stores several related fitted structures.

    ``side_edges[name]``
        Full side-edge arrays, with keys ``"positive"`` and ``"negative"``.
        Each side contains exactly ``n_bins + 1`` monotonically non-decreasing edge
        values, starting at ``0.0`` and ending at that side's fitted maximum magnitude.

    ``label_thresholds[name]``
        Convenience mapping used for fast scalar labeling. For each series:

        - ``ABk`` stores the positive upper threshold ``edge_{k+1}``
        - ``BLk`` stores the negative threshold ``-edge_{k+1}``

        These threshold values are sufficient to label new scalar values
        deterministically without recomputing quantiles or edge geometry.

    ``side_sources[name]``
        Metadata describing whether each fitted side was obtained from actual observed
        values or was mirrored from the opposite side to preserve schema completeness.

        For each series:
        - ``side_sources[name]["positive"]`` is ``"fit"`` or ``"mirrored"``
        - ``side_sources[name]["negative"]`` is ``"fit"`` or ``"mirrored"``

        This matters because one-sided fitting is a schema convention, not evidence of
        empirical symmetry.

    ``edges[name]``
        Backward-compatible alias of ``label_thresholds[name]``. This is preserved so
        older calling code does not break.

    Bin semantics
    -------------
    Let ``edge_0 = 0`` and ``edge_n = side_max`` for a given side.

    Positive-side labels:

    - ``AB_k`` covers values in ``(edge_k, edge_{k+1}]``

    Negative-side labels:

    - ``BL_k`` covers values in ``[-edge_{k+1}, -edge_k)``

    Explicit zero convention:

    - ``x == 0`` is assigned to ``AB0``

    That zero rule is arbitrary in the philosophical sense, but necessary in the
    engineering sense. A central pivot must have a deterministic home.

    One-sided data and mirroring
    ----------------------------
    If a series contains only positive or only negative observations, the missing side is
    mirrored from the observed side.

    This is a *schema-preserving convention*, not a claim of empirical symmetry.
    Mirroring exists so that the label space remains complete and stable even when only
    one side is present in the fitting sample.

    Feasibility clamp
    -----------------
    The requested step may be too large for the observed side span. If

        ``n_bins * step > side_max``

    then it is mathematically impossible to keep both the requested spacing and the
    requested number of bins while still ending at the observed maximum magnitude.

    In that case, the class reduces the effective step to:

        ``effective_step = side_max / n_bins``

    This preserves:

    - the bin count,
    - the zero pivot,
    - the endpoint at the observed maximum magnitude.

    This behavior is intentional and important. The class is designed to return a valid
    fitted discretizer whenever the data contain non-zero values, rather than failing
    merely because the preferred step was too ambitious for the available span.

    Boundary tolerance
    ------------------
    Scalar labeling can be sensitive to tiny floating-point residue, especially when
    values come from prior transforms. For this reason, the class uses a small absolute
    tolerance during scalar boundary checks.

    This tolerance:
    - does not alter the fitted edge geometry;
    - does not change the stored thresholds;
    - only affects how scalar values extremely close to zero or a threshold are assigned.

    Parameters
    ----------
    data : pandas.DataFrame | dict[str, pandas.Series]
        Input numeric series. If a DataFrame is provided, each column is treated as an
        independent series. Values are coerced to numeric, NaNs are dropped, and each
        series is cleaned independently.
    min_steps : dict[str, float]
        Strictly-positive per-series step sizes, typically estimated upstream. The keys
        must match the cleaned usable series exactly.
    n_bins : int, default 15
        Number of bins per side. Must be an integer >= 1.
    boundary_eps : float, default 1e-12
        Small absolute tolerance used only for scalar labeling robustness around zero
        and threshold comparisons. Must be finite and >= 0.

    Attributes
    ----------
    series_dict : dict[str, pandas.Series]
        Cleaned numeric input series after coercion and NaN removal.
    min_steps : dict[str, float]
        Normalized strictly-positive per-series step sizes.
    n_bins : int
        Number of bins per side.
    boundary_eps : float
        Absolute tolerance used only in scalar boundary decisions.
    side_edges : dict[str, dict[str, numpy.ndarray]]
        Fitted full edge arrays per series, with keys ``"positive"`` and ``"negative"``.
    label_thresholds : dict[str, dict[str, float]]
        Per-label thresholds used by :meth:`label_value`.
    side_sources : dict[str, dict[str, str]]
        Per-series metadata describing whether each side was directly fit or mirrored.
    edges : dict[str, dict[str, float]]
        Backward-compatible alias of ``label_thresholds``.
    """

    _DEFAULT_BOUNDARY_EPS = 1e-12

    def __init__(
        self,
        data: Union[pd.DataFrame, Dict[str, pd.Series]],
        *,
        min_steps: Dict[str, float],
        n_bins: int = 15,
        boundary_eps: float = _DEFAULT_BOUNDARY_EPS,
    ):
        """
        Initialize the discretizer with cleaned numeric series and validated steps.

        The constructor performs only normalization and validation. No fitting occurs
        until :meth:`fit` is called.

        Parameters
        ----------
        data
            DataFrame (columns are series) or dict[name -> pandas.Series].
        min_steps
            Mapping from series name to strictly-positive minimum step size. The mapping
            must cover exactly the cleaned series that survive numeric coercion and NaN
            removal.
        n_bins
            Number of bins per side. Must be >= 1.
        boundary_eps
            Small absolute tolerance used only during scalar labeling comparisons.
        """
        if isinstance(data, pd.DataFrame):
            raw_series = {col: data[col] for col in data.columns}
        elif isinstance(data, dict):
            raw_series = data
        else:
            raise TypeError("data must be a DataFrame or dict[str, pd.Series]")

        if not isinstance(n_bins, int) or n_bins < 1:
            raise ValueError("n_bins must be an integer >= 1")

        try:
            boundary_eps = float(boundary_eps)
        except (TypeError, ValueError) as exc:
            raise ValueError("boundary_eps must be float-convertible") from exc
        if (not np.isfinite(boundary_eps)) or (boundary_eps < 0.0):
            raise ValueError("boundary_eps must be finite and >= 0")

        # Clean each input series independently.
        #
        # This class is intentionally per-series at fit time. It does not require or
        # impose cross-series index alignment. Each series is treated as its own signed
        # value domain, provided it survives numeric coercion and NaN removal.
        cleaned: Dict[str, pd.Series] = {}
        for name, ser in raw_series.items():
            s = pd.to_numeric(ser, errors="coerce").dropna().astype(float)
            if not s.empty:
                cleaned[name] = s

        if not cleaned:
            raise ValueError("No usable series found after cleaning.")

        # Normalize min_steps early so the rest of the class can assume a clean float map.
        # This keeps validation centralized and avoids re-checking numeric convertibility
        # later inside fit-time logic.
        normalized_steps: Dict[str, float] = {}
        for name, value in min_steps.items():
            try:
                normalized_steps[name] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"min_steps[{name!r}] must be float-convertible") from exc

        if any((not np.isfinite(v)) or (v <= 0.0) for v in normalized_steps.values()):
            raise ValueError("all min_steps must be finite and > 0")

        # Require exact coverage of the cleaned usable series set.
        #
        # This class is downstream of step estimation. It should not guess missing step
        # definitions or silently ignore typoed keys. Exact key agreement is part of the
        # contract between the estimator stage and the discretizer stage.
        data_keys = set(cleaned)
        step_keys = set(normalized_steps)
        missing_steps = data_keys - step_keys
        unknown_keys = step_keys - data_keys
        if missing_steps:
            raise ValueError(f"min_steps missing for: {sorted(missing_steps)}")
        if unknown_keys:
            raise ValueError(f"min_steps contains unknown keys: {sorted(unknown_keys)}")

        self.series_dict: Dict[str, pd.Series] = cleaned
        self.min_steps: Dict[str, float] = normalized_steps
        self.n_bins = int(n_bins)
        self.boundary_eps = boundary_eps

        # Rich fitted structures.
        #
        # These are repopulated from scratch on each call to fit(). Their separation is
        # intentional:
        # - side_edges stores full geometric information,
        # - label_thresholds stores the faster scalar-labeling view,
        # - side_sources records whether each side was actually fit or mirrored.
        self.side_edges: Dict[str, Dict[str, np.ndarray]] = {}
        self.label_thresholds: Dict[str, Dict[str, float]] = {}
        self.side_sources: Dict[str, Dict[str, str]] = {}

        # Backward-compatible attribute retained for older code paths.
        self.edges: Dict[str, Dict[str, float]] = {}

    def _require_fitted(self) -> None:
        """
        Ensure the discretizer has been fitted.

        This helper centralizes the fitted-state check so callers do not duplicate
        slightly different checks in multiple public methods.
        """
        if not self.label_thresholds:
            raise RuntimeError("call fit() first")

    def _compute_side_edges(self, values: np.ndarray, step: float) -> np.ndarray:
        """
        Compute ``n_bins + 1`` edges for one strictly-positive magnitude side.

        Parameters
        ----------
        values : numpy.ndarray
            One-dimensional strictly-positive magnitudes for a single sign side.
            These should already be filtered so that zero and opposite-sign values are
            absent.
        step : float
            Requested minimum step size for this series. Must be strictly positive.

        Returns
        -------
        numpy.ndarray
            Monotonically non-decreasing edge array of length ``n_bins + 1`` with:

            - first edge exactly ``0.0``
            - last edge exactly equal to the side maximum magnitude
            - adjacent gaps that are at least the effective step whenever feasible

        Algorithm
        ---------
        1. Compute raw quantile cutpoints from 0% to 100%.
        2. Clamp the requested step to a feasible effective step.
        3. Forward pass:
           enforce minimum growth from the previous edge.
        4. Backward pass:
           re-anchor the final edge to ``vmax`` and re-enforce spacing while walking back.
        5. Final monotonicity and bounds safety pass.

        Notes
        -----
        The forward/backward adjustment is needed because quantile edges and hard spacing
        constraints can conflict. A single pass is not enough to preserve both endpoint
        anchoring and minimum local separation.
        """
        values = np.asarray(values, dtype=float)

        if values.ndim != 1:
            raise ValueError("values must be a one-dimensional array")
        if values.size == 0:
            raise ValueError("values must be non-empty")
        if np.any(~np.isfinite(values)):
            raise ValueError("values must be finite")
        if np.any(values <= 0.0):
            raise ValueError("values must contain strictly positive magnitudes only")
        if (not np.isfinite(step)) or (step <= 0.0):
            raise ValueError("step must be finite and > 0")

        vmax = float(np.max(values))

        # Feasibility clamp:
        # if the requested step is too large for the observed span, reduce it so that
        # exactly n_bins still fit between 0 and vmax.
        eff_step = min(float(step), vmax / self.n_bins)

        # Raw quantile cutpoints provide a data-adaptive starting geometry. They are only
        # the starting guess. The subsequent passes enforce hard geometric constraints.
        qs = np.linspace(0.0, 1.0, self.n_bins + 1)
        raw = np.quantile(values, qs)
        fixed = raw.astype(float).copy()

        # Forward pass:
        # force the zero pivot and ensure each subsequent edge is at least eff_step above
        # the previous one.
        fixed[0] = 0.0
        for i in range(1, len(fixed)):
            fixed[i] = max(fixed[i], fixed[i - 1] + eff_step)

        # Backward pass:
        # re-anchor the terminal edge to vmax, then walk backwards to ensure no edge
        # exceeds what the next edge can support while preserving the spacing rule.
        fixed[-1] = vmax
        for i in range(len(fixed) - 2, -1, -1):
            fixed[i] = min(fixed[i], fixed[i + 1] - eff_step)
            if i == 0:
                fixed[i] = 0.0

        # Final safety:
        # enforce monotonic non-decreasing order and clip numerical drift into [0, vmax].
        np.maximum.accumulate(fixed, out=fixed)
        fixed = np.clip(fixed, 0.0, vmax)

        return fixed

    def _build_label_thresholds(
        self,
        pos_edges: np.ndarray,
        neg_edges: np.ndarray,
    ) -> Dict[str, float]:
        """
        Convert full side-edge arrays into per-label thresholds used for scalar labeling.

        Parameters
        ----------
        pos_edges : numpy.ndarray
            Positive side edges of length ``n_bins + 1``.
        neg_edges : numpy.ndarray
            Negative-side magnitudes of length ``n_bins + 1``. These are stored as
            positive magnitudes internally and are converted to negative thresholds here.

        Returns
        -------
        dict[str, float]
            Mapping:

            - ``ABk`` -> positive upper threshold ``pos_edges[k + 1]``
            - ``BLk`` -> negative threshold ``-neg_edges[k + 1]``
        """
        thresholds: Dict[str, float] = {}
        for k in range(self.n_bins):
            thresholds[f"AB{k}"] = float(pos_edges[k + 1])
            thresholds[f"BL{k}"] = -float(neg_edges[k + 1])
        return thresholds

    def fit(self):
        """
        Fit signed bin edges for every cleaned series.

        For each series:
        - split values by sign;
        - fit positive and negative side magnitudes independently when both exist;
        - mirror one side when only one side exists;
        - reject all-zero series because no meaningful signed span exists;
        - store full edge arrays, threshold views, and side-source metadata.

        Returns
        -------
        DynamicBinner
            The fitted instance.
        """
        self.side_edges = {}
        self.label_thresholds = {}
        self.side_sources = {}
        self.edges = {}

        for name, ser in self.series_dict.items():
            step = self.min_steps[name]

            vals = np.sort(ser.values)
            pos = vals[vals > 0.0]
            neg_abs = -vals[vals < 0.0]

            if pos.size and neg_abs.size:
                pos_edges = self._compute_side_edges(pos, step)
                neg_edges = self._compute_side_edges(neg_abs, step)
                side_sources = {"positive": "fit", "negative": "fit"}
            elif pos.size:
                pos_edges = self._compute_side_edges(pos, step)
                neg_edges = pos_edges.copy()
                side_sources = {"positive": "fit", "negative": "mirrored"}
            elif neg_abs.size:
                neg_edges = self._compute_side_edges(neg_abs, step)
                pos_edges = neg_edges.copy()
                side_sources = {"positive": "mirrored", "negative": "fit"}
            else:
                raise ValueError(f"Series '{name}' contains only zeros.")

            thresholds = self._build_label_thresholds(pos_edges, neg_edges)

            self.side_edges[name] = {
                "positive": pos_edges,
                "negative": neg_edges,
            }
            self.label_thresholds[name] = thresholds
            self.side_sources[name] = side_sources

            # Preserve older attribute contract.
            self.edges[name] = thresholds

        return self

    def label_value(self, name: str, x: float) -> Union[str, float]:
        """
        Assign a deterministic signed-bin label to a single scalar value.

        Parameters
        ----------
        name : str
            Series name whose fitted thresholds should be used.
        x : float
            Value to label.

        Returns
        -------
        str | float
            Bin label such as ``"AB0"`` or ``"BL3"``, or ``numpy.nan`` when ``x`` is NaN.

        Boundary policy
        ---------------
        - Values very close to zero are treated as zero using ``boundary_eps``.
        - Positive values are assigned to the first ``AB`` threshold they do not exceed.
        - Negative values are assigned to the first ``BL`` threshold they are not below.
        - Values beyond the outermost fitted threshold are clamped to the last bin.

        Notes
        -----
        This method uses the threshold representation built during :meth:`fit`. It does
        not recompute edges and does not inspect the original fitting sample.
        """
        if pd.isna(x):
            return np.nan

        self._require_fitted()

        mapping = self.label_thresholds.get(name)
        if mapping is None:
            raise KeyError(f"No thresholds for '{name}' - unknown fitted series name.")

        x = float(x)

        # Robust zero convention. We intentionally treat tiny floating-point residue as
        # zero so that values conceptually at the pivot do not fall into arbitrary sides.
        if math.isclose(x, 0.0, abs_tol=self.boundary_eps):
            return "AB0"

        if x > 0.0:
            for k in range(self.n_bins):
                if x <= mapping[f"AB{k}"] + self.boundary_eps:
                    return f"AB{k}"
            return f"AB{self.n_bins - 1}"

        for k in range(self.n_bins):
            if x >= mapping[f"BL{k}"] - self.boundary_eps:
                return f"BL{k}"
        return f"BL{self.n_bins - 1}"

    def transform(self, subset: pd.DataFrame | None = None) -> pd.DataFrame:
        """
        Label one or more series and return raw plus label columns.

        Parameters
        ----------
        subset : pandas.DataFrame | None, default None
            Optional DataFrame to label. Only columns that were fitted are considered.
            If ``None``, the cleaned initialization series are labeled.

        Returns
        -------
        pandas.DataFrame
            DataFrame indexed by the union of all participating indices, with paired
            columns for each processed series:

            - ``<name>``     : raw numeric values
            - ``<name>_lab`` : corresponding labels

        Notes
        -----
        - Output is table-oriented and analysis-oriented.
        - The index is the union of all involved series indices.
        - Missing positions remain NaN in the raw column and NaN in the label column.
        """
        self._require_fitted()

        if subset is None:
            data = self.series_dict
        else:
            data = {
                name: pd.to_numeric(subset[name], errors="coerce").dropna().astype(float)
                for name in self.label_thresholds
                if name in subset
            }

        if not data:
            raise ValueError("No matching columns to label.")

        idx = None
        for s in data.values():
            idx = s.index if idx is None else idx.union(s.index)

        result = pd.DataFrame(index=idx)

        for name, series in data.items():
            aligned = series.reindex(idx)
            result[name] = aligned
            result[f"{name}_lab"] = aligned.map(lambda x: self.label_value(name, x))

        return result

    def export_artifact(self) -> Dict[str, Any]:
        """
        Export a structured, serialization-friendly fitted artifact.

        Returns
        -------
        dict[str, Any]
            A nested dictionary containing:
            - global configuration
            - normalized per-series steps
            - fitted side-edge arrays as Python lists
            - label thresholds
            - side-source metadata

        Notes
        -----
        This method does not write files and does not impose persistence policy. It only
        exposes the fitted result in a form that is easy to serialize by higher-level
        orchestration code.
        """
        self._require_fitted()

        per_series: Dict[str, Any] = {}
        for name in self.series_dict:
            per_series[name] = {
                "min_step": float(self.min_steps[name]),
                "side_edges": {
                    "positive": self.side_edges[name]["positive"].tolist(),
                    "negative": self.side_edges[name]["negative"].tolist(),
                },
                "label_thresholds": {
                    key: float(value)
                    for key, value in self.label_thresholds[name].items()
                },
                "side_sources": dict(self.side_sources[name]),
            }

        return {
            "n_bins": int(self.n_bins),
            "boundary_eps": float(self.boundary_eps),
            "series": per_series,
        }