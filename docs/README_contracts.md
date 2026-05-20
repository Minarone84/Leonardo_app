# Financial Tools Contract System

Version: v1.3
Date: 2026-05-20

## Purpose

The contract system is the structural truth for Leonardo financial tools. It exists so indicators, oscillators, and constructs can be added or audited without scattering metadata, naming rules, and renderability assumptions across compute, specs, controller, and GUI code.

## Ownership chain

```text
ToolContract manifests
→ family compute bridge/runtime
→ ft_naming identity façade
→ ft_specs metadata façade
→ HistoricalChartController apply/save boundary
→ HistoricalChartPanel chart-local study/style truth
→ ChartWorkspaceWidget pane contracts
→ panes
→ render surfaces
```

The contract layer does not compute and does not render. It describes the tool.

## Source layout

```text
financial_tools/
    ft_naming.py
    ft_specs.py

    tool_contracts/
        contracts.py
        registry.py
        validation.py
        manifests/
            indicators.py
            oscillators.py
            constructs.py

    naming_runtime/
        tokens.py
        hashing.py
        indicators.py
        oscillators.py
        constructs.py
        constructs_core.py
        bindings.py
        persistence.py
        registry.py

    specs_runtime/
        models.py
        inputs.py
        params.py
        behavior.py
        capabilities.py
        resolvers.py
        builder.py
        registry.py

    indicators/
        indicators.py
        indicators_runtime/

    oscillators/
        oscillators.py
        oscillators_runtime/

    constructs/
        constructs.py
        constructs_runtime/
```

## Stable public APIs

The following façade modules are the public surface:

```python
from leonardo.financial_tools.ft_naming import (
    build_source_token,
    get_indicator_signal_names,
    get_oscillator_signal_names,
    get_construct_signal_names,
    build_construct_instance_key,
    build_construct_filename,
)

from leonardo.financial_tools.ft_specs import (
    get_tool_spec,
    get_indicator_specs,
    get_oscillator_specs,
    get_construct_specs,
    tool_titles_by_kind,
    build_default_params,
    format_output_names,
    format_output_signals,
)
```

Family compute façades remain stable:

```python
from leonardo.financial_tools.indicators.indicators import Indicators, IndicatorRequest
from leonardo.financial_tools.oscillators.oscillators import Oscillators, OscillatorRequest
from leonardo.financial_tools.constructs.constructs import Constructs, ConstructRequest
```

## Non-negotiable rules

1. No tool without a `ToolContract`.
2. Contract manifests are source-controlled Python, not GUI-edited runtime JSON.
3. Runtime modules compute only.
4. Runtime modules must not define UI metadata.
5. `ft_naming.py` and `ft_specs.py` are public façades.
6. `naming_runtime` must not import compute runtime modules.
7. `specs_runtime` must not import compute runtime modules.
8. Specs must not invent output naming templates.
9. Runtime output keys must match naming resolver output.
10. Controller must not rename runtime outputs.
11. GUI must not reconstruct canonical identity.
12. Non-renderable outputs remain valid runtime outputs but must not become chart series.
13. Saved artifact metadata sidecars may consume contract/spec/naming metadata, but they must not become tool definitions.
14. Runtime JSON sidecars are artifact metadata and lineage records only; `ToolContract` manifests remain the source-controlled structural truth.
15. `analysis_usable=True` and `renderable=False` means an output may be persisted/chained but must not be rendered.
16. `accepts_empty_render_output=True` is the only contract-level opt-in for a chart-renderable tool to apply without renderable series.

## Saved artifact metadata sidecars

Leonardo now persists metadata for CSV-backed historical artifacts using adjacent `.meta.json` sidecars.

Normal CSV-backed artifacts use:

```text
<stem>.csv
<stem>.meta.json
```

This applies to OHLCV, indicator, oscillator, and construct CSV artifacts. Analysis Databases use `manifest.json` as the metadata sidecar for `dataframe.csv`.

The sidecar may include:

- artifact identity (`unique_id`, `artifact_id`, `artifact_uid`);
- market identity;
- CSV and metadata relative paths;
- first/last timestamps in `ts_ms`, UTC, and `Europe/Rome`;
- shape and per-column metadata;
- tool metadata from `ToolContract`;
- output metadata from `ft_specs.py`;
- canonical names and saved identity from `ft_naming.py`;
- params and bindings with explicit/inferred/unknown status;
- lineage, fingerprint, quality, and namespaced extension metadata.

Sidecars are consumers of contract data. They must not define new tool behavior, compute logic, render defaults, or naming templates.

## Adding a new indicator

1. Add an indicator contract in `tool_contracts/manifests/indicators.py`.
2. Implement compute in `indicators/indicators_runtime/<tool>.py`.
3. Register the runtime function in `indicators/indicators.py`.
4. Add naming support only if the output shape is not already covered.
5. Confirm `format_output_names()` and runtime result keys match.
6. Confirm the chart receives only renderable signals.

## Adding a new oscillator

1. Add an oscillator contract in `tool_contracts/manifests/oscillators.py`.
2. Implement compute in `oscillators/oscillators_runtime/<tool>.py`.
3. Register the runtime function in `oscillators/oscillators.py`.
4. Define semantic guide metadata in contracts/specs only when it is semantic metadata, not renderer behavior.
5. Keep pane bounds, guide rendering, fills, and threshold coloring downstream in chart-local visual policy.


## Current oscillator contract baseline

Current oscillator contracts include:

| Oscillator | Params | Runtime outputs | Visual guide metadata |
|---|---|---|---|
| RSI | `period` | `rsi_{period}` | fixed `0–100`, guides `70 / 50 / 30` |
| ARSI | `period`, `method`, `signal_period`, `signal_method` | `arsi_{period}_{method}`, `arsi_signal_{period}_{method}_{signal_period}_{signal_method}` | fixed `0–100`, guides `80 / 50 / 20` |
| MFI | `period` | `mfi_{period}` | fixed `0–100`, guides `70 / 50 / 30` |
| TDI RSI | `period`, `band_length`, `band_mult`, `fast_len`, `slow_len`, `fast_smo`, `slow_smo` | `tdirsi_fast_ma_*`, `tdirsi_slow_ma_*`, `tdirsi_up_*`, `tdirsi_dn_*`, `tdirsi_mid_*` | fixed `0–100`, guides `70 / 50 / 30` |
| SMI | `k_length`, `d_length` | `smi_{k_length}_{d_length}`, `smi_signal_{k_length}_{d_length}` | auto range, zero guide |
| OBV | none | `obv` | auto range |
| Volume | `period` / mean period | `volume`, `volume_mean_{period}` | auto range |

ARSI now follows the Ultimate RSI-style two-line structure: the main ARSI line plus a signal/mean line. The runtime may tolerate old saved params such as `boost_breakouts` for backward compatibility, but new public specs/contracts expose the current smoothing and signal parameters.

Concrete GUI colors, widths, histogram modes, threshold coloring, and pane fills remain downstream chart-local style/policy concerns. Contract manifests describe structural and semantic truth only.

## Adding a new construct

1. Add a construct contract in `tool_contracts/manifests/constructs.py`.
2. Implement compute in `constructs/constructs_runtime/<tool>.py`.
3. Register it in `constructs/constructs.py`.
4. Use structured input roles: `source`, `fast`, `mid`, `slow`, or `source_columns`.
5. Emit canonical runtime output names; do not rely on specs to invent names.
6. Confirm saved artifact identity includes binding/parameter identity where required.
7. Confirm gap honesty and deterministic alignment rules.

## Required validation

Run validation after every contract or runtime change:

```python
from leonardo.financial_tools.tool_contracts.validation import validate_all_contracts
validate_all_contracts(include_runtime=True, include_naming=True)
```

Also verify representative runtime outputs for indicators, oscillators, and constructs against naming/specs output metadata.

When changing sidecar metadata generation, also verify that saved artifact `.meta.json` files still preserve contract-derived `renderable`, `analysis_usable`, semantic role, params, bindings, and output structure without changing runtime CSV values.

When changing chart apply semantics, also verify accidental empty render payloads do not become chart-local studies unless the tool contract explicitly opts into empty render output.

## Current compatibility baseline

- non-construct indicators/oscillators use `default` as their binding slug;
- persistence helpers defensively normalize missing binding slugs;
- construct aliases such as `percent_angle` must resolve to canonical active keys such as `percent_span_angle` where supported;
- HCK `vwap_color` remains non-renderable utility output;
- braid ambient state is renderable and analysis-usable, while braid width/compression are non-renderable but analysis-usable;
- construct source-family metadata includes construct outputs as valid construct sources where allowed;
- `peaks_troughs` remains sparse marker/event output, not connected-line output.

## Execution context and UTC dependency contract

Financial tool execution environment is execution context, not normal tool identity. `ToolExecutionContext.environment` defaults to `historical`; realtime execution must be explicit and supported by the tool contract. Environment must not be inserted into params, canonical naming, saved artifact identity, render keys, or chart-local study identity.

`universal_trend_classifier` has explicit historical dependencies on saved/injected Peaks & Troughs columns for two detector purposes:

- directional trend stream: `peak_fractal_{trend_fractal_window}` and `trough_fractal_{trend_fractal_window}`;
- horizontal range stream: `peak_fractal_{range_fractal_window}` and `trough_fractal_{range_fractal_window}`.

The legacy `fractal_window` parameter remains a compatibility alias for the directional trend stream. The controller/source-resolution layer is responsible for loading the saved `peaks_troughs` artifact for the same market dataset, aligning it by `ts_ms` or `time`, and injecting all unique selected peak/trough columns before UTC compute. Trend and range dependency intents must be resolved independently even when both are satisfied by the same artifact. UTC runtime must remain compute-only and must not read artifact files directly.

UTC directional trend semantics are contractually constrained:

- uptrends start at troughs and end at peaks;
- downtrends start at peaks and end at troughs;
- opposite trends may share exactly one boundary swing/bar;
- opposite trends must not overlap beyond the shared boundary;
- invalid OHLC/source rows break active intervals and historical directional trend detection must not bridge NaN or malformed candle/source gaps;
- `hr_trend_max_gap` is horizontal-range continuity metadata and must not block directional uptrend/downtrend detection.

