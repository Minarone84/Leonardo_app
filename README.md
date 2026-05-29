# Leonardo

Python-first financial analytics application focused on deterministic market data, auditable financial tools, metadata-backed historical artifacts, analysis-database preparation, and chart-session-local visualization.

## Documentation map

Primary architecture documents live in `docs/`:

- `core_readme.md` — Core runtime, services, dataset access, artifact persistence, connection ownership, and apply/save boundaries.
- `README_historical_download.md` — Historical ingestion, OHLCV CSV storage, metadata sidecar behavior, exchange capability ownership, preflight planning, and Download Manager task monitoring.
- `README_contracts.md` — Financial-tools contract system (contracts, registry, validation).
- `DESIGN_financial_tools.md` — Financial tools system design (apply/save boundary, controller/panel/workspace integration).
- `construct_readme.md` — Construct naming and behavior policy.
- `study_readme.md` — Chart-session-local study system.
- `gui_readme.md` — GUI architecture, chart stack ownership, and Data Manager window boundaries.
- `DESIGN_historical_chart_v2.md` — Historical chart architecture (pan/zoom/autoscale/refill/render contracts).
- `Leonardo__Roadmap_V01.md` — Roadmap and change log.


## Current Historical Download Manager baseline — 2026-05-25

The Historical Download Manager is now a Core-supervised OHLCV ingestion flow. The GUI collects user input, displays exchange capabilities, requests preflight plans, shows the Confirm OHLCV Download dialog, opens the OHLCV Download Task monitor, and observes normalized audit events. Core owns execution through TaskManager, CoreBridge resolves the configured historical root and builds downloader requests from plain GUI intent, HistoricalDownloader owns planning/paging/persistence/validation, `ExchangeRegistry` owns exchange discovery and adapter factory lookup, and the exchange adapter owns venue-specific markets, timeframes, aliases, interval mappings, historical limits, and range-discovery behavior.

Important accepted behavior:

- multi-timeframe OHLCV selection and sequential batch execution;
- metadata-aware local file inspection and update-latest planning;
- preflight range discovery before confirmed download;
- task monitor progress, Stop/Cancel request handling, preliminary validation status, final recap, and batch validation summary;
- GUI `Limit = 0` means adapter/default page limit, and explicit values are clamped by the adapter maximum;
- historical capability display and downloader adapter acquisition route through the Core-registered `ExchangeRegistry`; Bybit remains the only default concrete adapter;
- OHLCV rewrites invalidate the matching `HistoricalDatasetService` dataset/slice cache through public Core/data APIs;
- post-write validation is preliminary reporting only; newly downloaded OHLCV metadata remains `validation.status = "unknown"` and `quality.validation_status = "not_validated"` until OHLCV Maintenance explicitly validates it;
- the final recap highlights preliminary `ERROR` and `WARNING` results and directs the user to Historical -> OHLCV Maintenance for validation, repair, or source correction;
- Historical Download Manager related windows/dialogs use a local +1 point font bump without changing the global `QApplication` font;
- Download Manager progress display is throttled/coalesced at the GUI layer: live progress and batch-progress updates are coalesced around 250 ms, pending state flushes on completion/error/cancel/final validation, and redundant same-state progress bar updates are suppressed;
- audit sinks normalize subsystem events so GUI snapshots and durable JSONL audit history consume one structured event shape;
- completed, failed, and cancelled tasks are removed from `TaskManager`'s active task map while remaining preserved in audit history.

## Current OHLCV Maintenance workflow — 2026-05-25

OHLCV Maintenance is a top-level Historical menu workflow for explicit dataset acceptance and repair. It lists stored OHLCV datasets, shows metadata/details and validation reports, supports checkbox-driven selection with Select All / Deselect All, and routes user intent through CoreBridge into `HistoricalOhlcvMaintenanceService`.

Accepted behavior includes:

- Analyze Checked runs `HistoricalDatasetValidator` through the data-layer service and stamps validation metadata;
- supported metadata/display statuses are `unknown`, `ok`, `modified`, `warning`, and `error`;
- Delete Selected deletes the exact `candles.csv` and adjacent `candles.meta.json` after confirmation;
- Rebuild Metadata rewrites only the metadata sidecar, not CSV values;
- Plan Repair computes explicit redownload ranges, and Execute Repair redownloads/replaces those ranges before revalidation;
- source-invalid repair outcomes are reported when the exchange returns data that still fails validation;
- Plan Source Correction and Apply Source Correction support conservative local correction for source-invalid candles with provenance records;
- `modified` means the dataset is valid after documented source correction and is accepted/loadable, but it is not raw exchange truth;
- the window opens at full usable height, half screen width, horizontally centered with the native title bar kept inside available screen geometry, and uses a local +1 point font bump.

The GUI remains display/intent only. Validation, deletion, metadata rebuild, repair orchestration, source correction execution, cache invalidation, and metadata stamping are data-layer responsibilities.

## Current Data Manager / Analysis Database workflow — 2026-05-28

Data Manager remains dataset/artifact oriented and separate from chart sessions. The current Analysis Database workflow includes:

- dataset selection through the CoreBridge/data-layer loadable OHLCV catalog, listing only `ok` and `modified` datasets and labeling modified datasets with `(Modified)`;
- no-loadable-dataset guidance that directs users to Historical -> OHLCV Maintenance;
- OHLCV preview verifies loadability through CoreBridge and uses the data-layer `csv_path` from the loadability report before bounded preview;
- `Database seed creator` for named draft manifests with a `SYMBOL_timeframe_` default prefix;
- Database seed creator remains the only user-facing Analysis Database creation workflow;
- checked saved artifact columns feed the `Database seed creator` only;
- no-whitespace, no-path-separator, same-market duplicate visible-name rejection for draft creation and rename;
- `Database Builder` for exactly-one-checkbox database selection, separate build and rebuild actions, explicit component editing, rename, delete, and preview;
- immutable `database_id` folder identity and mutable user-facing `display_name`;
- `Build Selected Database` opens a dedicated build dialog that auto-loads saved indicator, oscillator, and construct columns for visibility, highlights already-present database components for review, and materializes `dataframe.csv` from the selected database's saved manifest recipe without changing that recipe;
- `Rebuild Selected Database` rewrites `dataframe.csv` for an already materialized database from the same saved manifest recipe, preserving the same `database_id`, folder, display name, feature sources, feature columns, and recipe hash;
- `Edit Selected Database Components...` is the only workflow that intentionally changes an existing database recipe; it opens a dedicated component editor, auto-loads saved artifacts, highlights already-present Saved Artifact Columns with light green `#C8F7C5` background, black foreground, and bold font, supports explicit add/remove/replace actions, resets materialization to draft, and requires a later build;
- duplicate visible-name validation applies to creating new database drafts and renaming databases, not to materializing/rebuilding an existing database by `database_id`;
- save-only financial-tool artifact recipes and ordered recipe collections for reproducible full-dataset artifact calculation;
- `Create Recipes from Study Environment...` for exporting selected saved Study Environment studies into recipe definitions through a preview/report workflow;
- Saved Artifact Recipes, Saved Artifact Recipe Collections, Edit Analysis Database Components, and Extend Analysis Database from Collection dialogs open at 60% of usable screen width while preserving existing minimum-size intent;
- recipe-collection recovery controls for checking artifact status, regenerating planner-actionable missing/stale/unknown artifacts, rebuilding a linked Analysis Database when the collection carries `source_database_id`, and planning controlled recipe-collection updates through `Plan Updates...`;
- `Extend Database from Collection...` in the selected Analysis Database workflow for extending an existing database from current/resolved collection artifacts after C2 preview and `Confirm Database Extension`;
- Saved Indicators / Oscillators / Constructs selected-update controls: `Select All`, `Deselect All`, `Check Update`, and `Update Selected Artifacts`;
- Database Builder selected-update controls: `Select All`, `Deselect All`, `Check Update`, and `Update Selected Databases`;
- Data Manager opens maximized and uses the accepted compact M6F visual layout: Dataset and Calculate and Save Tool Outputs on the top row, DataFrame Preview and Saved Indicators / Oscillators / Constructs on the middle row, Data Checks / Metadata Tools plus Database seed creator on the lower-left area, and Database Builder on the lower-right area;
- Data Manager main widgets use the shared right-side `make_button_rack(...)` action layout with a 260px minimum action rack width, and the artifact calculator popup opens at 60% of usable screen width and height while preserving its minimum size;
- DataFrame Preview keeps source, row-limit, and visible timestamp information in the content header while its action remains in the shared button rack;
- saved artifact and Database Builder actions use the shared button rack so lists and details retain content width.

Data Manager only uses accepted OHLCV. The shared data-layer helpers `evaluate_ohlcv_dataset_loadability(...)`, `require_ohlcv_dataset_loadable(...)`, and `format_ohlcv_loadability_error(...)` enforce the same policy as `HistoricalDatasetService`: `ok` and `modified` are loadable; `unknown`, `not_validated`, `warning`, `error`, missing/unreadable metadata, metadata mismatch, missing CSV, and stale validation fingerprints are blocked. `ArtifactCalculationService._load_full_dataset_dataframe(...)`, `AnalysisDatabaseStore._load_selected_ohlcv_dataframe(...)`, and `ArtifactRecoveryPlanner._recalculation_blockers(...)` all enforce this before using source OHLCV.

GUI code collects user selections and presents dialogs. It must not manually rewrite `manifest.json`, move/delete `analysis_databases/{database_id}/`, invent persistence rules, classify artifact recovery/update state locally, parse `source_ohlcv.snapshot`, duplicate OHLCV validation/loadability policy, or replace Analysis Database components during build/rebuild/update. Recovery/update UI actions are intent surfaces only: status classification belongs to data-layer services such as `ArtifactRecoveryPlanner` and `DataManagerSelectedUpdateService`, artifact regeneration belongs to `ArtifactRecoveryRegenerator` / `ArtifactRecipeExecutor`, and Analysis Database materialization/rebuild belongs to `ArtifactRecoveryDatabaseRebuilder` / `AnalysisDatabaseStore`.

Saved artifact source selection in chart/Data Manager workflows consumes `.meta.json` column metadata when available. Valid sidecar `selectable` / `analysis_usable` metadata is the source-selection truth; CSV-header fallback is retained only for legacy, missing, or malformed sidecars.

Data Manager metadata/lineage hardening is implemented for generated outputs. Derived artifact sidecars and Analysis Database materialization metadata record source OHLCV provenance under `source_ohlcv.snapshot`, including source dataset identity, CSV/metadata paths, validation status, quality status, validation fingerprint, current CSV fingerprint, capture timestamp, and source-correction provenance when applicable. Analysis Database rebuild refreshes the materialization source snapshot instead of preserving stale source metadata. Recovery source-drift classification is implemented in the data/recovery layer: `ArtifactRecoveryPlanner` compares the recorded source snapshot against current accepted OHLCV truth, classifies source-drifted artifacts as stale, keeps legacy missing snapshots compatible as `freshness_unknown` / lineage unknown, and blocks actionability when current OHLCV is not loadable. Source-drifted artifacts are planner-actionable only through the existing explicit recovery execution path. `AnalysisDatabaseStore.materialization_source_ohlcv_drift_report(...)` exposes read-only materialization source-drift reporting.

The recipe-collection update workflow is implemented for saved recipe collections. `DataManagerUpdateService` builds read-only `DataManagerUpdatePlan` objects from a recipe collection, maps `ArtifactRecoveryPlanner` statuses into plan items/actions/blockers, includes linked Analysis Database materialization source-drift checks when `source_database_id` is present, and preserves recipe collection order for planned artifact actions. The Data Manager `Plan Updates...` dialog displays the service-produced plan/report data, executes selected actions or all actionable actions through `execute_update_plan(...)`, delegates artifact regeneration to `ArtifactRecoveryRegenerator` / `ArtifactRecipeExecutor` / `ArtifactCalculationService`, delegates linked database rebuilds to `ArtifactRecoveryDatabaseRebuilder` / `AnalysisDatabaseStore`, reports completed/skipped/failed/blocked action results, and refreshes saved artifact and Analysis Database lists after execution. This workflow remains recipe-collection scoped; dataset-wide update scanning, arbitrary dependency graph inference, and background task/progress integration remain future work.

Selected artifact/database update workflows are implemented through `DataManagerSelectedUpdateService`. `Check Update` is read-only: it plans selected saved artifact status for indicators, oscillators, and constructs, or selected Analysis Database status for existing databases, and returns service-produced `current`, `old`, `unknown`, `blocked`, `error`, and database-only `draft` states. `OLD` means known stale/source-drifted and actionable; missing, legacy, or incomplete lineage is not treated as OLD by default, and draft Analysis Databases are shown as DRAFT rather than OLD. `Update Selected Artifacts` and `Update Selected Databases` execute only checked OLD/actionable actions from the latest plan. Artifact updates delegate through existing recovery/regeneration/calculation ownership; database updates rebuild existing materialized databases through Analysis Database store/materialization ownership while preserving `database_id`, folder identity, display name, manifest recipe, feature sources, feature columns, and component list. Selected-update dialogs provide preflight, synchronous running state, and terminal reports; they do not promise mid-operation cancellation, and status markings are GUI display state from the latest check rather than persisted metadata.

Construct Batch Builder is implemented as a Data Manager-only workflow inside Calculate and Save Tool Outputs when the selected family is Constructs. It supports unary source expansion for `derivative`, `angle`, `percent_span_angle`, and `angle_momentum`, plus binary `delta` with explicit direction `delta = minuend - subtrahend`. Preview Plan is read-only and reports planned, existing, blocked, and error items using structured saved-artifact metadata, `selectable` / `analysis_usable` eligibility, timestamp-safe alignment, common-range checks, and read-only existing-recipe detection. Save Recipes persists selected planned recipes through `ArtifactRecipeStore`; Save as Collection persists/reuses recipes first and then saves an ordered collection through `ArtifactRecipeCollectionStore`. Calculate Artifacts persists/reuses selected recipes first and executes them sequentially through `ArtifactRecipeExecutor` / `ArtifactCalculationService` ownership. The GUI displays preflight, running, and terminal reports and refreshes lists; it does not directly write CSV or `.meta.json`, does not calculate artifacts directly, and does not extend, build, or rebuild Analysis Databases automatically. Generic Construct Batch does not support `braids`, `braid_instability`, `trap_area`, or `dynamic_binning`; those remain future structured-template or special-case workflows.

Research Suite artifact save now preserves reproducibility at the same time as saved values. Saving an artifact from the historical chart Financial Tools flow saves or reuses the corresponding recipe in the Data Manager-visible `ArtifactRecipeStore(historical_root=...)` partition-local `artifact_recipes` store before artifact persistence continues. Equivalent recipes reuse deterministic identity, and artifact sidecars record non-identity recipe metadata: `recipe_id`, `recipe_hash`, and `recipe_hash_short`.

Study application remains chart-local and non-persistent. Saving a Study Environment or Workspace Snapshot does not directly persist recipes.

Financial Tools Apply now opens a chart-panel-owned preflight/progress dialog before execution. The dialog shows the tool title, chart/dataset context, and `Input bars to process: N`. Cancel is available before execution starts; once the synchronous Apply begins, progress is indeterminate, Cancel is disabled, and OK becomes available after success or failure. Apply remains chart-local and non-persistent.

The Study Style editor now exposes Apply / OK / Cancel. Style editor Apply commits the current style to the live chart while keeping the dialog open; OK applies and closes; Cancel closes without applying further unapplied edits and does not roll back changes already explicitly committed through Apply. White / `#FFFFFF` remains available in the style palettes. Style changes remain visual-only and do not recompute studies.

Saved Study Environments can now be planned into Data Manager artifact recipe definitions. The internal `StudySetupRecipeExportPlanner` inspects serialized studies, supports important-only filtering, classifies candidates as exportable / conditional / blocked / skipped, and produces recipe payload and collection draft previews without writing or calculating artifacts. `StudySetupRecipeExportPersistenceService` persists only selected/all exportable candidates through `ArtifactRecipeStore` and can optionally save an ordered recipe collection through `ArtifactRecipeCollectionStore`. The Data Manager dialog displays the plan and persistence report; it does not calculate artifacts, execute recipes, create Analysis Databases, or export Workspace Snapshots.

Recipe collections can now extend an existing selected Analysis Database when their expected artifacts are already current. `RecipeCollectionDatabasePlanner` consumes recovery status and resolves only up-to-date artifacts into source/column previews; missing, stale, source-drifted, freshness-unknown, blocked, duplicate-column, and cross-market cases are reported instead of included. The GUI uses `RecipeCollectionDatabaseService.extend_database_from_plan(...)` only after the user confirms `Confirm Database Extension`; the retained backend create method is a data-layer compatibility contract, not a user-facing collection workflow. Missing or stale artifacts remain handled through `Plan Updates...`; no update execution, artifact calculation, recipe execution, or `dataframe.csv` materialization happens in this flow.

`AnalysisDatasetGeographyPolicy` reports whether an Analysis Database manifest or planned component set contains the minimum dataset terrain: OHLC base, explicit Volume artifact, Braids, Peaks & Troughs, and UTC / Universal Trend Classifier. It also reports raw OHLCV volume presence, explicit Volume artifact presence, semantic raw-volume plus Volume-artifact duplication risk, and opportunistic `dataset_role` mismatches. This policy is diagnostic only; database creation is not blocked by geography by default, and `dataset_role` is a user-facing hint rather than proof of tool identity.

Analysis Suite now has its first read-only GUI surface. AS1 added the backend boundary, `AnalysisSuiteDatasetReadinessService`, with JSON-safe `AnalysisSuiteDatasetReadinessReport` and `AnalysisSuiteDatasetCatalogReport` outputs.

AS2 added `AnalysisSuiteWindow`, opened from `Analysis -> Analysis Suite`, while `Analysis -> Data Manager` remains the separate preparation workflow. The window consumes AS1 readiness reports and lists Analysis Databases with readiness status, `strict_ready`, `can_preview`, market identity, row/column counts, first/last timestamps, source drift status, topology/geography status, missing topology, blockers, warnings, and errors. It can route users back to Data Manager, but it is read-only: readiness policy stays in AS1, and the GUI does not inspect manifests, dataframes, or `source_ohlcv.snapshot` for policy.

AS3 added `AnalysisSuiteDataframePreviewService`, and AS4 wired bounded preview into `AnalysisSuiteWindow`. The read-only Analysis Suite catalog now supports Head and Tail previews through the AS3 service with AS1 `can_preview` gating, service-enforced row limits of default `100` and max `500`, JSON-safe rows, raw `ts_ms`, and `ts_utc` / `ts_rome` display fields when `ts_ms` exists. Previewable does not mean analysis-ready: non-strict datasets may be previewed only when AS1 allows it, and readiness status, warnings, and blockers remain visible. The GUI does not load `dataframe.csv` directly and does not call `AnalysisDatabaseStore.load_dataframe(...)` for preview policy.

AS5 added `AnalysisSuiteTargetPlanner`, a backend-only read-only target/label preview planner. A target is a future-dependent value or event the Analysis Suite wants to predict, classify, measure, or explain; a label is the generated per-row target series aligned back to timestamp `t`, so features at `t` predict the label at `t`. `AnalysisSuiteTargetDefinition` and `AnalysisSuiteTargetPreviewReport` currently support future return regression, `(close[t + N] - close[t]) / close[t]`, and future direction classification, `up` / `down` / `flat` from explicit thresholds. `horizon_bars` must be positive, means `N` dataframe rows forward in the Analysis Database timeframe, writes `label_end_ts_ms` for the future row used, and leaves the last `N` rows unavailable.

AS5 target previews are gated by AS1 `can_preview`; non-strict but previewable datasets may run while preserving warnings and blockers. Reports include row counts, available/unavailable label counts, first/last available timestamps, regression stats or class distribution, sample rows, blockers/warnings/errors, and leakage metadata. Label outputs are `target_only`, `future_derived`, and `feature_eligible = false`; they are not appended to `dataframe.csv`, not ordinary feature columns, and AS6 feature-set planning rejects target-only/future-derived label outputs. AS5 has no GUI wiring, target-definition persistence, label persistence, Analysis Project/Run/Report stores, model training, signal generation, trading logic, artifact calculation, recipe execution, OHLCV repair, or Analysis Database mutation/materialization.

AS6 added `AnalysisSuiteFeatureSetPlanner`, a backend-only read-only feature-set planner with `AnalysisSuiteFeatureCandidate`, `AnalysisSuiteFeatureSetDefinition`, and `AnalysisSuiteFeatureSetPreviewReport`. A feature set is a validated selection of input columns from one Analysis Database for a future target/analysis workflow; it is not the dataset, model config, Analysis Run, or report. A feature candidate is a manifest-derived Analysis Database column considered for feature use and classified as `eligible`, `blocked`, `warning`, `reserved`, or `unknown`; classification uses manifest/artifact metadata rather than raw CSV header guessing.

AS6 lists candidates with `list_feature_candidates(...)`, validates ordered selections with `validate_selected_features(...)`, and returns read-only previews through `preview_feature_set(...)`. Eligible groups are current-row OHLC base columns (`open`, `high`, `low`, `close`), raw volume as `raw_volume` when present, explicit Volume artifact outputs, indicators, oscillators, constructs, topology artifacts, construct batch outputs, and non-renderable but `analysis_usable` outputs. Group names are `alignment`, `base_ohlc`, `raw_volume`, `volume`, `indicators`, `oscillators`, `constructs`, `topology`, `construct_batch`, and `unknown`. Raw volume is not equivalent to the explicit Volume artifact, and current-row `close[t]` remains eligible for future-return targets when otherwise valid.

AS6 rejects target output columns, label columns, `target_only`, `future_derived`, `feature_eligible = false`, the exact AS5 target output column, `ts_ms` as a normal feature, unknown metadata, and non-selectable or non-analysis-usable utility/internal columns. AS1 `can_preview` gates planning; non-strict but previewable datasets may still be planned with warnings/blockers preserved. Reports include candidates, selected/rejected features, group summaries, leakage summaries, blockers, warnings, and errors, and remain JSON-safe. AS6 has no GUI wiring, feature-set persistence, `FeatureSetStore`, Analysis Project/Run/Report stores, model training, signal generation, trading logic, artifact calculation, recipe execution, OHLCV repair, or Analysis Database mutation/materialization.

Strict-ready still requires a readable manifest, materialized database, readable `dataframe.csv`, dataframe hash/metadata consistency when available, clean materialization source-OHLCV drift status, and complete minimum topology. Still out of scope: Analysis Projects/Runs/Reports, model training, signal generation, trading logic, artifact calculation, database build/rebuild/materialization, feature-set persistence, OHLCV repair, CoreBridge APIs, and manifest/dataframe/sidecar writes. Stale or incomplete datasets must be routed back to Data Manager or OHLCV Maintenance workflows instead of repaired inside Analysis Suite.

## Current Historical Chart / Study workflow — 2026-05-26

The historical chart stack is now hardened around the ownership chain:

```text
Core dataset truth → controller/session truth → panel chart-local study truth → workspace pane/layout contracts → pane handoff → renderer execution
```

Accepted behavior includes:

- dataset selection is Core/data-backed through `HistoricalDatasetService` catalog APIs and `CoreBridge`, not GUI folder-walking;
- chart creation uses the loadable OHLCV catalog and only accepts `ok` or `modified` datasets; `HistoricalDatasetService.open_dataset(...)` enforces the final gate before loading;
- dataset-open and resident-slice async results are marshalled back to the GUI thread and guarded against stale dataset/open-generation/request results;
- controller apply keeps full-dataset compute truth separate from resident-local render truth;
- Financial Tools Apply is confirmed through a preflight/progress dialog that reports `Input bars to process: N`, supports pre-execution cancel, shows indeterminate progress during synchronous Apply, and reports success/failure before OK is enabled;
- renderable outputs are the only outputs that become chart series; accidental empty render payloads fail unless the tool explicitly allows empty render output;
- non-renderable but `analysis_usable` outputs remain valid temporary construct sources without entering the renderer;
- save writes full-dataset artifacts with explicit params, bindings, and durable saved-source lineage where available;
- chart save, saved-dependency lookup, and chart-opened `FinancialToolsManagerWindow` paths use the configured historical storage root from runtime config;
- active construct saved identity includes deterministic `__h<hash8>` identity;
- style changes invalidate static render caches through public workspace/pane/surface contracts instead of panel reach-through into renderer internals;
- `Series.values` consumers honor the `Sequence` contract;
- `HistoricalDatasetService` exposes explicit dataset-cache invalidation so OHLCV rewrites do not leave stale in-memory timelines/slices;
- runtime projection aligns financial-tool output by explicit `ts_ms` / `time` / non-positional index data before falling back to the legacy full-dataset/no-timeline positional invariant;
- chart save and Data Manager/recipe calculation share `result_to_save_dataframe(...)` for consistent full-dataset saved value conversion, including boolean output preservation and gap honesty;
- historical UTC dependency preparation is centralized in `utc_dependency_sources.py` for chart apply/save and `ArtifactCalculationService`, while UTC runtime remains compute-only;
- `ArtifactRecoveryPlanner` shares UTC required-column intent resolution and performs read-only blocker checks for missing or duplicate `ts_ms` / `time` dependency join keys.
- `ChartStudyInstance` carries `StudyUserMetadata` with `important`, `description`, and `dataset_role`;
- study `user_metadata` is semantic/user-facing metadata only and does not affect computation, rendering, style, runtime, artifact identity, or recipe identity;
- study serialization/deserialization, Study Environments, and Workspace Snapshots preserve `user_metadata`, while old payloads load with default metadata values;
- applied chart study controls focus on chart-local actions such as Style, Edit, and Remove;
- Save Study Environment / Update existing Study Environment includes per-study metadata controls for Important, Dataset role, and Description;
- metadata selected in the save/update dialog is applied to the saved serialized Study Environment payload and does not mutate the live chart registry;
- the Study Environment Manager remains the post-save editor for saved Study Environment metadata.

M6/M6B completed release-check/test reconciliation and full uploaded test validation without production-code changes.

## Current Research Suite / Workspace layout workflow — 2026-05-26

Research Suite is the user-facing historical chart research/design area. It is still implemented internally by `HistoricalDataManagerWindow`, and internal classes, schema fields, IDs, and store paths intentionally remain stable. Historical chart sessions support an 8-slot embedded workspace without changing chart-session, controller, renderer, data, or financial-tool ownership. The Research Suite opens maximized so the chart workspace is immediately usable.

Accepted workspace behavior includes:

- New Chart selection uses the CoreBridge/HistoricalDatasetService loadable catalog, shows only `ok` and `modified` OHLCV, labels modified datasets, and displays OHLCV Maintenance guidance when no validated datasets are available;
- blocked datasets cannot bypass the selector because `HistoricalDatasetService.open_dataset(...)` refuses non-loadable OHLCV before chart loading;
- up to 8 embedded historical chart panels;
- stable logical slot identity ordered as `1-2`, `3-4`, `5-6`, `7-8`;
- detached charts reserve their original slot and dock back into that same slot;
- chart-level Position controls can move a chart to another slot or swap with an occupied slot while protecting reserved detached slots;
- two visualization modes: `Scroll 4` for scrolling beyond the first four visible charts, and `Fit 8` for fitting all embedded charts into the usable workspace;
- a checkable `Pan Anchor` quick action, off by default, that synchronizes horizontal panning across active charts in the same Research Suite using timestamp-center recentering;
- adaptive visual layout by embedded chart count:
  - 1 chart → one full-widget chart;
  - 2 charts → one row with two equal columns;
  - 3 charts → one full-width chart above two equal-width charts;
  - 4 charts → 2x2;
  - 5 charts → 2x2 plus one full-width bottom chart;
  - 6 charts → 3x2;
  - 7 charts → 3x2 plus one full-width bottom chart;
  - 8 charts → 4x2.

This is Historical Workspace shell behavior only. It does not move dataset truth, study truth, pane contracts, rendering semantics, or persistence ownership out of their existing layers.

Current compact-layout behavior also includes:

- compact chart-area margins and embedded-grid gaps;
- reduced splitter handle width and pane spacing;
- reduced price/volume/oscillator plot padding while preserving readable axes;
- `Scroll 4` / `Fit 8` moved to the `Window` menu;
- a top-right menu-bar label showing the current visualization mode;
- unchanged historical chart-space domain padding.

Pan Anchor is horizontal-only. It does not synchronize zoom, vertical scale, autoscale/manual-y state, renderer internals, studies, notebooks, or saved presets. Programmatic navigation such as Notebook/POI/PT Go and Workspace Snapshot load does not become a pan-sync source.

## Current Notebook / Workspace Snapshot workflow — 2026-05-26

Research Suite includes a workspace-linked Notebook workflow for chart analysis notes and runtime chart annotations.

Accepted notebook behavior includes:

- `Notes` menu actions for creating, opening, saving, loading notebooks, and opening `Notebook Manager...`;
- Notebook Manager owns assignment/unassignment, notebook descriptions/last-save visibility, assigned-workspace summaries, and confirmed notebook deletion;
- notebook persistence through `HistoricalNotebookStore` under `chart_presets/notebooks`, outside the notebook window itself;
- notebooks may be saved without being assigned to any workspace snapshot;
- Workspace Snapshots store only an optional `notebook_ref`, never embedded notebook content;
- deleting an assigned notebook through Notebook Manager clears referencing workspace snapshot `notebook_ref` values, but deleting a Workspace Snapshot never deletes the referenced notebook;
- chart tabs are keyed by dataset identity (`exchange`, `market_type`, `symbol`, `timeframe`), while chart position remains display metadata only;
- structured notebook sections for Notes, Potential Trades, and Points of Interest;
- Notes rows use `Delete | Date / Time | Note` and do not expose Go navigation;
- Potential Trades rows use `Go | Delete | Date / Time | Direction | Starting Price | Target % Movement | Closing Price | Outcome | Note`;
- Potential Trades direction is empty by default, with explicit `Long` / `Short` choices required for marker projection;
- Point of Interest rows use `Go | Delete | Date / Time | Title | Description`;
- row-level Delete actions require confirmation before removal;
- row-level Go actions for Potential Trades and POIs emit `chart_key + ts_ms` and let `HistoricalDataManagerWindow` route chart centering through the existing chart panel/controller path;
- runtime POI and Potential Trade chart markers are notebook-driven annotations, not hidden studies and not financial-tool outputs;
- Potential Trade markers render as Long green upward arrows below bars or Short red downward arrows above bars;
- notebook-level `annotation_settings` persist `poi_marker_offset`, `pt_long_marker_offset`, and `pt_short_marker_offset`;
- notebooks support explicit Save as new and Update existing modes through `HistoricalNotebookStore.update_notebook(...)`;
- Update existing preserves `notebook_id` and `created_at_ms`, advances `updated_at_ms`, recomputes `content_hash`, and atomically overwrites through the store;
- Create New Notebook clears the prior loaded identity before refreshing workspace charts;
- Save as new creates a distinct notebook identity and does not repoint existing Workspace Snapshot `notebook_ref` values;
- dirty notebooks prompt with Save / Don't Save / Cancel before close or replacement, including Create New Notebook, Load Notebook, assigned notebook replacement, and Workspace Snapshot assigned-notebook replacement;
- Save uses the existing save flow and proceeds only after success, Don't Save proceeds without writing, and Cancel aborts the close/load/replace action;
- notebook free-text fields support basic formatting through compact palettes beside Add Note, Add Trade, and Add Point of Interest;
- rich-text controls target only notebook description, note text, trade note text, POI title, and POI description; dates, timestamps, numeric fields, IDs, dataset identity, symbol/timeframe fields, and direction/outcome selectors remain plain;
- notebook free-text fields keep plain-text values and may also store formatted HTML in parallel fields such as `description_html`, `note_html`, and `title_html`;
- old plain-text notebooks continue to load, and formatted HTML fields participate in notebook `content_hash` when present;
- notebook assignment/unassignment refreshes the visible notebook indicator immediately for the current workspace snapshot, without reloading the workspace;
- a compact menu-bar `Notebook` quick action before the Study Environment actions opens the notebook assigned to the current workspace snapshot when a valid `notebook_ref` is available.

Study Environments remain notebook-free. Notebook data belongs to the notebook store and Workspace Snapshot association belongs to `notebook_ref` only.

## Current saved Study Environment / Workspace Snapshot management — 2026-05-26

Saved Study Environment and Workspace Snapshot save dialogs support both Save as new and Update existing. Save as new remains the default. Update existing requires selecting an existing saved item, preloads its name/description, reuses the existing `setup_id` or `snapshot_id`, preserves `created_at_ms`, advances `updated_at_ms`, recomputes `content_hash`, and overwrites atomically through the preset stores without creating a duplicate file. Workspace Snapshot updates preserve existing `notebook_ref` behavior.

Saved Study Environment and Workspace Snapshot load dialogs also expose confirmed Delete actions.

Accepted behavior includes:

- the Study Environment save action can save a new environment or update the selected environment through `ChartStudySetupStore.update_setup(...)`;
- the Workspace Snapshot save action can save a new snapshot or update the selected snapshot through `HistoricalWorkspaceSnapshotStore.update_snapshot(...)`;
- GUI dialogs collect user intent only; preset stores own persistence, hashing, timestamps, identity preservation, and atomic writes;
- the Study Environment load action can delete the selected saved environment through `ChartStudySetupStore.delete_setup(setup_id)`;
- deleting a saved Study Environment does not remove currently applied chart studies and does not affect Workspace Snapshots;
- the Workspace Snapshot load action can delete the selected snapshot through `HistoricalWorkspaceSnapshotStore.delete_snapshot(snapshot_id)`;
- deleting a Workspace Snapshot does not delete referenced notebooks, datasets, saved studies, or saved artifacts;
- Workspace Snapshot delete confirmation explicitly mentions a referenced notebook when `notebook_ref` is present;
- Workspace Snapshot load shows a preflight dialog with snapshot name, description, chart count, chart recap, notebook assignment, and a replacement warning before restore;
- confirmed load switches to an indeterminate loading state during the existing synchronous restore;
- restore remains synchronous, non-cancellable after it starts, and non-transactional;
- delete dialogs refresh their list and clear stale selection/details after successful deletion.

Research Suite also exposes `Manage Study Environments...` and `Manage Workspace Snapshots...`. `StudyEnvironmentManagerDialog` lists saved environments, shows contained studies, edits top-level name/description, edits per-study serialized `user_metadata` (`important`, `dataset_role`, `description`), preserves study params/style/bindings, and deletes through `ChartStudySetupStore` APIs. The Save/Update Study Environment dialog is the pre-save metadata placement point; the manager is the post-save editor. `WorkspaceSnapshotManagerDialog` lists saved snapshots, shows saved charts and studies, displays `notebook_ref`, edits top-level name/description, and deletes through `HistoricalWorkspaceSnapshotStore` APIs. Embedded Workspace Snapshot study metadata is read-only in RS4.

No recipe creation, artifact calculation, Workspace Snapshot export, assigned-notebook deletion, or Analysis Database creation is part of these dialogs.

## Current Oscillator / ARSI workflow — 2026-05-20

Oscillator outputs now include the accepted Volume and upgraded ARSI behavior:

- Volume is an oscillator-pane artifact with `volume` histogram bars and `volume_mean_{period}` as a configurable rolling mean line.
- ARSI is an Ultimate RSI-style two-line oscillator with `arsi_{period}_{method}` and `arsi_signal_{period}_{method}_{signal_period}_{signal_method}`.
- ARSI defaults use configurable `EMA/SMA/RMA/TMA` smoothing, a signal/mean line defaulting to orange `#FF5D00`, and `80 / 50 / 20` guide levels.
- RSI and MFI remain single-line bounded oscillators with the generic `70 / 50 / 30` guide policy.
- Dynamic oscillator signal names resolve to their canonical chart-local style defaults before style state is persisted.
- Threshold-aware oscillator coloring splits line segments at the actual threshold crossing and leaves neutral regions controlled by the user-selected series color.

These are chart/apply/runtime contract changes only where appropriate. Renderer code remains execution-only, and GUI colors/widths remain downstream chart-local style defaults.

## Release packaging guardrails (GUI)

When producing a GUI distribution zip, exclude development artifacts:

- `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.git/`

Recommended scripts (in the GUI package):

- `gui/tools/release_checks.py` — static contract + hygiene checks
- `gui/tools/package_clean_zip.py` — produces a clean zip after checks pass

## Refactor baseline — 2026-04-20

This documentation package records the post-refactor architecture baseline:

- financial tools split into bridge/runtime packages with contract-backed naming/spec façades;
- financial tools now carry explicit `ToolExecutionContext` so historical and future realtime execution can be distinguished without polluting params, naming, saved identity, or render keys;
- CSV-backed historical artifacts now use `.meta.json` sidecars for artifact identity, metadata, lineage, fingerprint, and quality metadata;
- Data Manager and Analysis Database workflows prepare analysis-ready datasets without becoming chart sessions; the current workflow separates `Database seed creator`, `Build Selected Database`, `Rebuild Selected Database`, and explicit `Edit Selected Database Components...`; durable rename/delete/build/rebuild semantics remain in `AnalysisDatabaseStore`, component changes remain in the explicit component editor path, no-space/duplicate-name policy applies to create/rename, and rebuilds materialize selected databases from their saved manifests without replacing artifact components;
- Universal Trend Classifier historical mode consumes shared-helper-injected Peaks & Troughs event columns for independent directional-trend and horizontal-range detection, preserves invalid-gap honesty, and keeps compute-only runtime ownership with renderer-only drawing; recovery planning shares the same dependency-intent resolver while remaining read-only;
- Core/GUI feed dependency removed from the Bybit feed boundary;
- historical dataset service exposes explicit public timeline/columns/dataframe APIs;
- historical chart controller, panel, workspace, panes, and renderers are physically split while preserving public import façades;
- workspace owns Autoscale/manual-y and pane contracts;
- viewport remains horizontal camera only;
- panes remain handoff boundaries;
- renderers remain execution-only.
- historical saved-artifact source selection is sidecar-metadata-driven, runtime projection prefers explicit timeline/index alignment, and full-dataset save conversion is shared through `result_to_save_dataframe(...)`.
