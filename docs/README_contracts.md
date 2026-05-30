# Financial Tools Contract System

Version: v1.12
Date: 2026-05-30

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

Analysis Database creation is a user-facing `Database seed creator` workflow. Recipe collections may extend a selected Analysis Database through C2 planning and `RecipeCollectionDatabaseService.extend_database_from_plan(...)`, but the GUI does not expose collection-driven database creation. Extension does not materialize databases, calculate artifacts, or execute recipes.

Selected artifact and Analysis Database updates are planned through `DataManagerSelectedUpdateService`, not by GUI-side sidecar or manifest policy. `Check Update` is read-only and reports service-owned statuses. `Update Selected Artifacts` may execute only checked OLD/actionable artifact actions through the existing recovery/regeneration/calculation path. `Update Selected Databases` may rebuild only checked OLD/actionable materialized databases through Analysis Database materialization ownership; DRAFT is not OLD, components are not added/removed/replaced, and unknown lineage is not treated as actionable by default.

Data Manager Construct Batch planning consumes contract/spec/naming metadata through data-layer services. Generic batch supports unary `derivative`, `angle`, `percent_span_angle`, and `angle_momentum`, plus binary `delta` with report semantics `delta = minuend - subtrahend`. Source eligibility uses saved artifact `selectable` / `analysis_usable` metadata; non-renderable but analysis-usable outputs may be valid sources, while non-selectable utility columns are blocked. Timestamp-safe alignment requires shared timestamp keys and common range evidence, not equal row count alone. Preview planning writes nothing, Save Recipes writes through `ArtifactRecipeStore`, Save as Collection writes through `ArtifactRecipeCollectionStore`, and Calculate Artifacts delegates through `ArtifactRecipeExecutor` / `ArtifactCalculationService` after recipes are saved or reused. Construct Batch does not create or materialize Analysis Databases, and the GUI does not write artifact CSV or sidecar files directly.

Analysis Suite dataset readiness is a read-only consumer contract. `AnalysisSuiteDatasetReadinessService` evaluates Data Manager Analysis Databases before Analysis Suite consumes readiness data, returning `AnalysisSuiteDatasetCatalogReport` and `AnalysisSuiteDatasetReadinessReport` objects. `AnalysisSuiteWindow`, opened from `Analysis -> Analysis Suite`, displays those service-produced reports while `Analysis -> Data Manager` remains the separate preparation workflow. Readiness statuses are `ready`, `draft`, `missing_dataframe`, `stale_source`, `incomplete_topology`, `corrupt_manifest`, `corrupt_dataframe`, `blocked`, and `error`. Strict-ready requires a readable manifest, materialized database, readable and hash-consistent dataframe when hash metadata exists, clean materialization source-OHLCV drift status, and complete minimum topology: accepted OHLC base, explicit Volume artifact, Braids artifact, Peaks & Troughs artifact, and UTC / Universal Trend Classifier artifact. Raw OHLCV volume does not satisfy the explicit Volume artifact requirement. `AnalysisSuiteDataframePreviewService` owns bounded Head/Tail dataframe preview, gates preview through AS1 `can_preview`, enforces default `100` / max `500` row limits, returns JSON-safe rows, preserves raw `ts_ms`, and adds `ts_utc` / `ts_rome` when `ts_ms` exists. Previewable does not mean analysis-ready; non-strict datasets may be previewed only when AS1 allows it, with warnings and blockers preserved. The Analysis Suite GUI is read-only, does not inspect manifests/dataframes/source snapshots for policy, does not load `dataframe.csv` directly, does not call `AnalysisDatabaseStore.load_dataframe(...)`, and does not calculate artifacts, rebuild/materialize databases, repair OHLCV, edit components, write manifests, write dataframes, export previews, or add Analysis Project/Run/Report persistence.

Analysis Suite target preview is also read-only. `AnalysisSuiteTargetPlanner` consumes AS1 readiness and creates in-memory `AnalysisSuiteTargetPreviewReport` diagnostics from `AnalysisSuiteTargetDefinition` rules. A target is a future-dependent value or event the Analysis Suite wants to predict, classify, measure, or explain; a label is the generated per-row target series aligned back to timestamp `t`, so features at `t` predict the label at `t`. AS5 supports future return regression, `(close[t + N] - close[t]) / close[t]`, and future direction classification, `up` / `down` / `flat` from explicit thresholds. `horizon_bars` must be positive, means `N` dataframe rows forward in the Analysis Database timeframe, keeps labels aligned to `t`, records `label_end_ts_ms` for the future row used, and marks the last `N` rows unavailable. The planner gates dataframe access through AS1 `can_preview`; non-strict previewable datasets may run while preserving readiness warnings and blockers. Reports include database identity, target definition, row count, available/unavailable label counts, first/last available timestamps, regression stats or class distribution, sample rows, blockers/warnings/errors, and leakage metadata. Label outputs are `target_only`, `future_derived`, and `feature_eligible = false`; they are not persisted, not written to `dataframe.csv`, not ordinary feature columns, and AS6 feature-set planning must reject target-only/future-derived outputs. AS5 does not add GUI wiring, TargetDefinitionStore, label files, Analysis Project/Run/Report stores, model training, signals, trading logic, artifact calculation, recipe execution, OHLCV repair, or Analysis Database mutation.

Analysis Suite feature-set planning is read-only. `AnalysisSuiteFeatureSetPlanner` returns `AnalysisSuiteFeatureSetPreviewReport` diagnostics from manifest metadata using `AnalysisSuiteFeatureCandidate` and the non-persisted `AnalysisSuiteFeatureSetDefinition` preview model. A feature set is a validated selection of input columns from one Analysis Database for a future target/analysis workflow; it is not the dataset, model config, Analysis Run, or report. A feature candidate is a manifest-derived column classified as `eligible`, `blocked`, `warning`, `reserved`, or `unknown`; eligibility is metadata-driven rather than based on raw CSV headers.

AS6 provides `list_feature_candidates(...)`, `validate_selected_features(...)`, and `preview_feature_set(...)`. Eligible groups include current-row OHLC base columns (`open`, `high`, `low`, `close`), raw volume as `raw_volume` when present, explicit Volume artifact outputs, indicators, oscillators, constructs, topology artifacts, construct batch outputs, and non-renderable but `analysis_usable` outputs. Groups are reported as `alignment`, `base_ohlc`, `raw_volume`, `volume`, `indicators`, `oscillators`, `constructs`, `topology`, `construct_batch`, and `unknown`. Raw volume is not equivalent to an explicit Volume artifact, and current-row `close[t]` remains eligible for future-return targets when otherwise valid.

AS6 rejects `ts_ms` as a normal feature because it is the alignment key. It also rejects target output columns, label columns, `target_only`, `future_derived`, `feature_eligible = false`, the exact AS5 target output column, unknown metadata in MVP, and non-selectable or non-analysis-usable internal/utility columns. Planning is gated by AS1 `can_preview`; `strict_ready = false` datasets may still be planned when `can_preview = true`, with warnings and blockers preserved. Reports include candidates, selected/rejected features, group summaries, leakage summaries, blockers, warnings, and errors, and they remain JSON-safe. AS6 does not add GUI wiring, feature-set persistence, `FeatureSetStore`, Analysis Project/Run/Report stores, model training, signals, trading logic, artifact calculation, recipe execution, OHLCV repair, or Analysis Database mutation.

Analysis Suite diagnostic reporting is a read-only pre-analysis consumer contract. `AnalysisSuiteDiagnosticReportService` composes an AS1 readiness report, an AS5 target preview report, and an AS6 feature-set preview report into a JSON-safe `AnalysisSuiteDiagnosticReport` with status `ready`, `warning`, `blocked`, or `error`. `AnalysisSuiteFeatureColumnDiagnostic` reports selected accepted feature column consistency, including dtype and missingness summaries, only after AS6 has accepted the feature. AS7 reports dataset readiness, target coherence, feature-set validity, label availability, enough-row/label checks, target stats or class distribution, selected-feature diagnostics, leakage blockers, and combined blockers/warnings/errors. It reads dataframe values only for AS6-accepted selected-feature consistency checks and does not treat raw CSV headers as feature truth. AS7 does not add GUI wiring, persisted diagnostic reports, Analysis Project/Run/Report stores, target/label/feature-set persistence, model training, signals, trading logic, artifact calculation, recipe execution, OHLCV repair, or Analysis Database mutation/materialization.

Analysis Suite POI/family planning is a read-only AS8 consumer contract. `AnalysisSuitePoiFamilyPlanner` evaluates in-memory `AnalysisSuitePoiDefinition` and `AnalysisSuitePoiFamilyDefinition` inputs and returns bounded JSON-safe `AnalysisSuitePoiOccurrencePreviewReport` and `AnalysisSuitePoiFamilyPreviewReport` diagnostics. `AnalysisSuitePoiCondition`, `AnalysisSuitePoiOccurrence`, and `AnalysisSuitePoiFamilyMembership` describe condition rules, event occurrences, and family membership results. Public methods are `preview_poi_occurrences(...)`, `preview_family(...)`, and `validate_family_definition(...)`. Supported POI event kinds are `sparse_event`, `boolean_true`, `value_equals`, and `transition`; supported family condition operators are `equals`, `not_equals`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `is_null`, and `not_null`. Conditions are AND-style MVP rules with same-row and fixed-lookback checks; complex expression trees and rolling-window pattern mining are not implemented. AS8 gates through AS1 readiness or optional AS7 diagnostic reports, blocks `can_preview == false`, blocks blocked/error AS7 diagnostics, and allows non-strict previewable datasets while preserving warnings and blockers. It validates POI source and condition columns through manifest metadata before dataframe reads, rejects target-only, future-derived, and `feature_eligible = false` inputs when metadata exists, reads dataframe values only for read-only occurrence and condition preview, and does not treat raw CSV headers as event truth. AS8 does not persist POI definitions or families, add GUI wiring, create POI/Project/Run/Report stores, compute Peaks & Troughs, compute UTC, compute Braids, classify roads, build genome paths, train models, generate signals, backtest, calculate artifacts, execute recipes, repair OHLCV, or mutate Analysis Databases.

Analysis Suite genome/path planning is a read-only AS9 consumer contract. `AnalysisSuiteGenomePathBuilder` evaluates in-memory `AnalysisSuiteGenomeEncodingDefinition` and `AnalysisSuiteGenomeComponentDefinition` inputs and returns bounded JSON-safe `AnalysisSuiteGenomePathPreviewReport` diagnostics. `AnalysisSuiteStaticBinRule`, `AnalysisSuiteGenomeSnapshot`, and `AnalysisSuiteGenomePath` describe explicit static bin thresholds, encoded timestamp states, and ordered path samples. Public methods are `validate_encoding_definition(...)`, `preview_paths(...)`, and `preview_paths_for_poi_family(...)`.

AS9 supports `identity_numeric`, `categorical`, `boolean_symbolic`, `static_bin`, and `variation_direction` encodings. `identity_numeric` keeps numeric values JSON-safe. `categorical` converts state values into string tokens. `boolean_symbolic` maps boolean or true-ish/false-ish values to symbolic `true`, `false`, or missing tokens. `static_bin` uses explicit `AnalysisSuiteStaticBinRule` thresholds only and does not fit bins, learn quantiles, train adaptive thresholds, or inspect future rows. `variation_direction` compares only values at `t` and `t - lookback` and returns `increasing`, `decreasing`, `flat`, or `missing`; it is a conservative MVP descriptor, not the full Variation Analyzer engine.

AS9 gates through AS1 readiness or optional AS7 diagnostic reports, blocks `can_preview == false`, blocks blocked/error AS7 diagnostics, and allows non-strict previewable datasets while preserving warnings. It validates component source columns through AS6 feature-set reports or manifest metadata when available, blocks `ts_ms`, target-only, future-derived, and `feature_eligible = false` inputs when metadata exists, reads dataframe values only for read-only genome/path preview, and does not treat raw CSV headers as semantic genome truth. Row-anchored paths preserve ordered snapshots as `G(t-k) ... G(t)`, invalid or early anchors are reported with structured blockers, and optional AS8 POI/family anchoring uses matched family membership samples without recomputing POIs. AS9 does not persist genome definitions, encoding definitions, or paths; does not add GUI wiring or genome stores; does not implement Dynamic Binner fitting, full Dynamic Binner, full Variation Analyzer, road classification, outcome scoring, white-box rule discovery, rule mining, model training, signals, backtesting, artifact calculation, recipe execution, OHLCV repair, or Analysis Database mutation.

The sidecar may include:

- artifact identity (`unique_id`, `artifact_id`, `artifact_uid`);
- market identity;
- CSV and metadata relative paths;
- first/last timestamps in `ts_ms`, UTC, and `Europe/Rome`;
- shape and per-column metadata;
- tool metadata from `ToolContract`;
- output metadata from `ft_specs.py`;
- per-column source-selection metadata such as `selectable`, `renderable`, and `analysis_usable` when available;
- canonical names and saved identity from `ft_naming.py`;
- params and bindings with explicit/inferred/unknown status;
- lineage, fingerprint, quality, and namespaced extension metadata;
- source OHLCV provenance under `source_ohlcv.snapshot` for generated derived artifacts when available;
- non-identity recipe metadata (`recipe_id`, `recipe_hash`, `recipe_hash_short`) for artifacts saved from reproducible recipe-backed flows when available.
- OHLCV validation metadata when the artifact is `ohlcv/candles.csv`.

Sidecars are consumers of contract data. They must not define new tool behavior, compute logic, render defaults, or naming templates. Valid sidecar column metadata is also the source-selection truth for saved artifacts: non-renderable but analysis-usable/selectable outputs may be selected as analytical sources, while non-selectable utility columns must not be exposed merely because they exist in the CSV header.

The `source_ohlcv.snapshot` entry is metadata/lineage only. It records the accepted OHLCV source used for calculation, including source validation/fingerprint and source-correction provenance where applicable. Recovery classification may consume it to detect source OHLCV drift, but it does not change canonical artifact naming, params, bindings, recipe identity, or tool behavior. Recipe metadata keys identify the saved or reused recipe associated with a saved artifact; they do not become artifact identity fields.

For OHLCV, validation metadata is an acceptance contract owned by the historical data layer. `ok` and `modified` are loadable; `unknown`, `not_validated`, `warning`, `error`, missing/unreadable metadata, metadata mismatch, stale fingerprints, missing validation fingerprints, and missing CSV are blocked. Download-time validation is preliminary reporting only and does not certify a dataset as accepted.

Download Manager progress throttling is a GUI display concern. Coalescing live progress updates must not change downloader/provider requests, OHLCV CSV output, metadata sidecars, validation/loadability, or audit event contracts.

## Serialized chart study metadata

Serialized chart studies may include `user_metadata` from `StudyUserMetadata`:

- `important`
- `description`
- `dataset_role`

This metadata is user-facing semantic context. It must not define financial-tool contracts, runtime outputs, renderability, chart style, saved artifact identity, recipe identity, or Analysis Database geography truth. `dataset_role` may support warnings and review context, but tool identity and geography detection must use structured tool/source metadata where available.

Save/Update Study Environment writes selected metadata into cloned serialized study payloads before `ChartStudySetupStore` persistence. This is writeback to the saved payload, not mutation of the live chart registry, and it does not change the serialized `user_metadata` schema.

## Saved Research Suite object update identity

Updating an existing Study Environment preserves its internal `setup_id`, preserves `created_at_ms`, advances `updated_at_ms`, recomputes `content_hash`, and replaces the stored study payload through `ChartStudySetupStore.update_setup(...)`. The internal schema/model name remains `ChartStudySetup`.

Updating an existing Workspace Snapshot preserves its `snapshot_id`, preserves `created_at_ms`, advances `updated_at_ms`, recomputes `content_hash`, replaces the stored workspace/chart payload through `HistoricalWorkspaceSnapshotStore.update_snapshot(...)`, and preserves existing `notebook_ref` behavior. Update-existing is an overwrite of the selected saved item, not a new saved item.

Updating an existing Notebook preserves its `notebook_id`, preserves `created_at_ms`, advances `updated_at_ms`, recomputes `content_hash`, and replaces stored notebook content through `HistoricalNotebookStore.update_notebook(...)`.

Research Suite managers use store-owned update/delete APIs. The Study Environment Manager may edit serialized study `user_metadata`; the Workspace Snapshot Manager displays embedded study metadata read-only in RS4.

Workspace Snapshot load preflight/loading and notebook indicator refresh are GUI state flows. They do not alter snapshot schema, store persistence, notebook persistence, or `notebook_ref` semantics.

Restore remains synchronous, non-cancellable after it starts, and non-transactional.

## Notebook rich-text persistence

Notebook free-text fields preserve plain-text compatibility. Existing fields such as `description`, note/trade `note`, POI `title`, and POI `description` remain populated with plain text for compatibility, search, and fallback display.

Formatted free-text content may be stored in optional parallel HTML fields:

- `description_html`
- `note_html`
- `title_html`

Old notebooks without these HTML fields remain valid. IDs, timestamps, dates, numeric fields, dataset identity, symbol/timeframe fields, and direction/outcome selectors remain plain. Notebook `content_hash` includes optional HTML fields when they are present.

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

When changing sidecar metadata generation, also verify that saved artifact `.meta.json` files still preserve contract-derived `renderable`, `analysis_usable`, semantic role, params, bindings, and output structure without changing runtime CSV values. When changing saved-source selection, also verify that valid sidecar `selectable` / `analysis_usable` metadata wins over CSV-header guessing and that legacy fallback does not override valid metadata.

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

The legacy `fractal_window` parameter remains a compatibility alias for the directional trend stream. The controller/source-resolution layer is responsible for loading the saved `peaks_troughs` artifact for the same market dataset, aligning it by `ts_ms` or `time`, and injecting all unique selected peak/trough columns before UTC compute. Trend and range dependency intents must be resolved independently even when both are satisfied by the same artifact. UTC runtime must remain compute-only and must not read artifact files directly. Execution paths share UTC Peaks & Troughs dependency preparation through the data-layer helper, while recovery planning shares only the dependency-intent/required-column resolver and remains read-only, including blocker checks for missing or duplicate dependency join keys.

UTC directional trend semantics are contractually constrained:

- uptrends start at troughs and end at peaks;
- downtrends start at peaks and end at troughs;
- opposite trends may share exactly one boundary swing/bar;
- opposite trends must not overlap beyond the shared boundary;
- invalid OHLC/source rows break active intervals and historical directional trend detection must not bridge NaN or malformed candle/source gaps;
- `hr_trend_max_gap` is horizontal-range continuity metadata and must not block directional uptrend/downtrend detection.
