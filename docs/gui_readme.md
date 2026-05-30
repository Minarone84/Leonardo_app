# Leonardo GUI Architecture (Current State)

Version: v3.37
Date: 2026-05-30

## Overview

The Leonardo GUI is the visualization layer for both historical and real-time charting.

It is built around a modular chart engine that supports:

- resident slices for large historical datasets
- a shared horizontal viewport camera
- workspace-owned price-pane autoscale and manual-y behavior
- fixed chart-space domain policy for historical sessions
- detachable chart sessions
- pane-managed rendering
- chart-local study styling
- chart-local oscillator visual policy
- Notebook workflow for notes, Potential Trades, POIs, runtime chart annotations, and workspace snapshot notebook references
- Historical workspace Pan Anchor for optional horizontal pan synchronization across active charts
- confirmed delete workflows for saved Study Environments, Workspace Snapshots, notebook rows, and notebooks
- per-study metadata controls in Save Study Environment / Update existing Study Environment
- Save as new / Update existing flows for saved Study Environments, Workspace Snapshots, and Notebooks
- Research Suite managers for saved Study Environments and Workspace Snapshots
- Data Manager Study Environment to recipe export, selected Analysis Database extension from recipe collections, selected artifact/database update workflows, and Construct Batch Builder workflows
- OHLCV Maintenance for explicit validation, repair, source-invalid reporting, and source correction
- accepted OHLCV gating for Research Suite and Data Manager workflows
- centralized runtime diagnostics

The GUI supports two deployment models:

- embedded historical chart panels
- floating chart windows

Both deployment models share the same chart engine and the same chart-session behavior.

---

## Architectural Separation

The GUI separates these concerns:

- chart-session state
- chart-space and viewport camera behavior
- workspace pane/layout and pane-contract behavior
- shell window behavior
- diagnostics and runtime visibility
- financial tool workflow
- chart-local style and pane-local visual policy

This separation allows:

- detachable sessions without state loss
- independent evolution of GUI, compute, and storage
- stable chart behavior during pan and zoom
- optional horizontal pan synchronization without moving zoom, vertical scale, or renderer ownership
- duplicate same-config studies without collapsing chart-local identity
- chart-local study lifecycle without renderer ownership creep
- centralized runtime visibility without moving ownership into the GUI

---

## Core Runtime Integration

The GUI runs strictly downstream of Core.

Core owns:

- application lifecycle
- service lifecycle
- background task supervision
- runtime state tracking
- audit event emission
- historical dataset access and slicing
- financial-tool computation and persistence

The GUI must treat Core as the single source of truth for runtime and data behavior.

The GUI must never:

- mutate runtime state directly
- manage service lifecycle
- own async orchestration
- own connection lifecycle
- reconstruct historical datasets locally
- move computation or persistence semantics into rendering code

---

## Runtime State Access

The GUI reads runtime state through the Core interface.

Available runtime information includes:

- application status
- active services and lifecycle state
- background task activity
- realtime activation state
- tracked window state
- connection runtime state
- session runtime identity

Connection runtime state includes:

- connection identity
- connection lifecycle status
- last error

Important rule:

The GUI must never infer or reconstruct connection state locally.
Connection state must always be read from `StateStore`.

---

## Connection Lifecycle Boundary

Connection lifecycle is owned by orchestration code, not by the GUI.

The GUI:

- may request realtime start and stop through `CoreBridge`
- must observe connection state through runtime state
- must not manage connection lifecycle directly
- must not own feed futures or async feed execution

`CoreBridge` owns the active realtime future and ignores completion callbacks from stale futures that are no longer the active feed future.

Adapters remain transport-only and must not expose lifecycle or runtime state.

The current `MainWindow` feed controls remain a temporary integration surface, not a permanent connection-management interface.

---

## Runtime Visibility Layer

The Runtime Inspector is the centralized GUI diagnostics surface.

It is:

- read-only
- polling-based
- thread-safe
- driven by Core runtime snapshots
- separate from runtime mutation and orchestration

Current tabs include:

- Runtime
- Connections
- Tasks
- Audit
- Windows

Important rule:

The Runtime Inspector must not mutate runtime state, infer hidden state, own lifecycle, or become a surrogate orchestration layer.

---

## Window Tracking Alignment

The GUI Window Manager tracks all top-level windows:

- `MainWindow`
- `HistoricalDataManagerWindow`
- `HistoricalChartWindow`
- `FinancialToolsManagerWindow`
- `DataManagerWindow`
- `HistoricalDownloadWindow`
- `OhlcvMaintenanceWindow`
- Runtime Inspector window

Embedded chart panels are not tracked as top-level windows.

`WindowManager` is a GUI-owned QObject. Registering it in `AppContext` provides service lookup only and does not transfer lifecycle ownership to Core.

Window lifecycle events are reflected into Core runtime state so Core maintains a consistent system-wide view of active windows.

---


## Historical Download Manager

`HistoricalDownloadWindow` is a top-level managed GUI window for OHLCV ingestion. It is an intent and observation surface, not an execution owner and not a chart session.

Responsibilities include:

- collecting exchange, market, symbol, timeframe, optional range, and optional limit input;
- displaying supported exchanges, markets, and timeframes supplied through CoreBridge/capability callbacks backed by Core `ExchangeRegistry`;
- requesting Core-owned preflight plans through CoreBridge;
- submitting plain download intent to CoreBridge, which resolves the configured historical root and builds downloader requests internally;
- showing the Confirm OHLCV Download dialog before execution;
- opening the OHLCV Download Task monitor for progress, preliminary validation, cancellation, and final recap display;
- showing preliminary `ERROR` results in bold red and preliminary `WARNING` results in warning styling;
- showing that newly downloaded OHLCV remains `validation.status = "unknown"` and `quality.validation_status = "not_validated"`;
- directing users to Historical -> OHLCV Maintenance for explicit validation, repair, or source correction;
- throttling/coalescing live progress display in the GUI layer while forcing pending progress to flush on completion, error, cancel, and final validation;
- applying a local +1 point font bump to Historical Download Manager related windows/dialogs without changing the global application font;
- requesting Stop/Cancel through CoreBridge.

It must not:

- hardcode exchange-specific market/timeframe lists;
- own Bybit aliases, interval mappings, or request limits;
- build or reinterpret historical range plans locally;
- execute downloads directly;
- own async task lifecycle or cancellation truth.

Download Manager progress throttling is display-only. `HistoricalDownloadWindow._poll_progress()` still observes Core audit snapshots through a GUI `QTimer`; live `download progress` / `download batch progress` events are coalesced around 250 ms, the latest pending progress is retained, final states flush immediately, and redundant same-state progress-bar updates are suppressed without changing downloader/provider/OHLCV persistence semantics.

Accepted limit behavior:

- GUI `Limit = 0` means adapter/default page limit.
- Explicit user limits are request intent only; Core/downloader clamps them to the selected adapter's maximum.
- Bybit's `1000` candle historical page maximum is adapter truth, not GUI truth.

The ownership chain for historical downloads is:

```text
HistoricalDownloadWindow
→ CoreBridge capability / command boundary
→ ExchangeRegistry capability provider for exchange display / adapter lookup
→ TaskManager
→ HistoricalDownloader
→ BaseExchange capability contract
→ concrete exchange adapter
→ CsvOHLCVStore + HistoricalDatasetValidator
→ HistoricalDatasetService cache invalidation
→ normalized audit events
→ OHLCV Download Task monitor
```

---

## OHLCV Maintenance Window

`OhlcvMaintenanceWindow` is a top-level managed Historical menu window for manual OHLCV acceptance and maintenance. The GUI displays dataset state and user intent; `HistoricalOhlcvMaintenanceService` owns validation, deletion, metadata rebuild, repair orchestration, source correction execution, cache invalidation, and metadata stamping.

Accepted behavior includes:

- listing OHLCV datasets with checkbox-driven selection plus Select All / Deselect All;
- showing metadata/details and validation reports;
- Analyze Checked through CoreBridge -> `HistoricalOhlcvMaintenanceService` -> `HistoricalDatasetValidator`;
- persisted validation statuses `unknown`, `ok`, `modified`, `warning`, and `error`, with row styling;
- confirmed Delete Selected for the exact `candles.csv` and adjacent `candles.meta.json`;
- Rebuild Metadata that rewrites only the metadata sidecar;
- Plan Repair and Execute Repair with repair confirmation, progress, recap, and post-repair validation;
- source-invalid repair outcome reporting when exchange data still fails validation;
- Plan Source Correction and Apply Source Correction with explicit confirmation and provenance-recorded local correction;
- `modified` display/status for datasets valid after documented source correction;
- initial geometry at full usable screen height, half available screen width, horizontally centered with the native title bar inside available geometry;
- a local +1 point font bump covering the table, labels, buttons, details, validation report, repair recap, and source-correction plan/execution content.

It must not parse CSV, implement validation rules, write metadata directly, or move correction/repair logic into GUI code.

---

## Data Manager Window

`DataManagerWindow` is a top-level managed window opened from the main-window Analysis menu.

It is dataset/artifact oriented, not a chart session.

Responsibilities include:

- selecting accepted/loadable historical OHLCV partitions through CoreBridge/data-layer catalog surfaces;
- listing saved OHLCV, indicator, oscillator, construct, artifact recipe, recipe collection, and Analysis Database artifacts;
- creating Analysis Database draft seeds through the `Database seed creator` widget;
- building existing draft/unmaterialized Analysis Databases through a dedicated build dialog opened from `Build Selected Database`;
- rebuilding already materialized Analysis Databases through `Rebuild Selected Database`;
- explicitly editing Analysis Database components through `Edit Selected Database Components...`;
- saving full-dataset artifact recipes and recipe collections through the save-only financial-tool workflow;
- creating recipes from saved Study Environments through `Create Recipes from Study Environment...`;
- checking recipe-collection recovery status, regenerating planner-actionable artifacts, and rebuilding linked Analysis Databases through data-layer recovery services;
- planning and executing recipe-collection-scoped updates through `Plan Updates...` and `DataManagerUpdateService`;
- planning selected saved artifact updates through `Check Update` and executing checked OLD/actionable artifact actions through `Update Selected Artifacts`;
- planning selected Analysis Database updates through `Check Update` and executing checked OLD/actionable database rebuild actions through `Update Selected Databases`;
- extending a selected existing Analysis Database from current recipe-collection artifacts through `Extend Database from Collection...`;
- previewing tabular artifacts in a read-only dataframe view;
- exposing explicit data-check / metadata-restore workflows.

## Analysis Suite Window

`AnalysisSuiteWindow` is a top-level managed read-only catalog window opened from `Analysis -> Analysis Suite`. `Analysis -> Data Manager` remains the separate Data Manager preparation workflow.

The window consumes `AnalysisSuiteDatasetReadinessService` reports. It lists Analysis Databases with readiness status, `strict_ready`, `can_preview`, market identity, row and column counts, first and last timestamps, materialization source-drift status, and topology/geography status. Selecting a row shows database id, display name, manifest path, dataframe path, readiness fields, source OHLCV drift status, missing topology, blockers, warnings, and errors.

Allowed actions are `Refresh Catalog`, row detail display, the `Data Preview`, `Target Preview`, `Feature Set`, `Diagnostic Report`, `POI / Family Preview`, and `Genome Path Preview` tabs, `Open Data Manager`, and close. `Open Data Manager` is routing only; Analysis Suite does not perform repair, build, update, or calculation work itself.

Bounded preview supports Head and Tail modes through `AnalysisSuiteDataframePreviewService`. The preview button is enabled only when the selected readiness report has `can_preview == True`. Row limits are enforced by the service with default `100` and max `500`; the preview table is read-only, and refresh or selection changes clear stale preview state. Preview reports preserve readiness status, `strict_ready`, warnings, blockers, errors, row limits, returned row count, dataset and preview timestamp ranges, raw `ts_ms`, and `ts_utc` / `ts_rome` display fields when `ts_ms` exists.

AS-GUI-1 exposes AS5, AS6, and AS7 as the first interactive Analysis Suite setup workflow. The `Target Preview` tab lets the user choose future return regression or future direction classification, set `horizon_bars`, set direction up/down thresholds, and run `AnalysisSuiteTargetPlanner`. The report area displays label availability, regression stats or class distribution, leakage metadata, blockers, warnings, and errors. Target definitions remain in memory and are not persisted.

The `Feature Set` tab calls `AnalysisSuiteFeatureSetPlanner`. It lists manifest-derived feature candidates with status, group, reason, and source metadata where available; lets the user select candidate features; provides `Select All Eligible` and clear-selection actions; and displays selected/rejected features, group summaries, leakage summaries, blockers, warnings, and errors. `Select All Eligible` selects eligible candidates only. Feature sets remain in memory and are not persisted.

The `Diagnostic Report` tab requires a selected Analysis Database, a current target preview, and a current feature-set preview. It calls `AnalysisSuiteDiagnosticReportService` and displays final `ready`, `warning`, `blocked`, or `error` status with dataset, target, feature, leakage, label, missingness, dtype, blocker, warning, and error diagnostics. Diagnostic reports remain in memory and are not persisted.

AS-GUI-2 exposes AS8 as the first POI/family GUI workflow. The `POI / Family Preview` tab contains a POI Definition section for POI key, display name, POI type, source column, event kind, event value, and previous value. It supports AS8 event kinds `sparse_event`, `boolean_true`, `value_equals`, and `transition`, calls `AnalysisSuitePoiFamilyPlanner.preview_poi_occurrences(...)`, and displays status, row count, occurrence count, first/last occurrence timestamps, sample occurrences, blockers, warnings, and errors. POI definitions remain in memory and are not persisted.

The same tab contains a Family Conditions section for family key/name and simple AND-style condition rows with column, operator, value/values, `lookback_bars`, required flag, and label. It supports AS8 condition operators `equals`, `not_equals`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `is_null`, and `not_null`, calls `AnalysisSuitePoiFamilyPlanner.preview_family(...)`, and displays occurrence count, matched/unmatched counts, sample memberships, condition result summaries, blockers, warnings, and errors. POI family definitions remain in memory and are not persisted.

AS-GUI-3 exposes AS9 as the first genome/path GUI workflow. The `Genome Path Preview` tab contains an Encoding Definition section for encoding key/name, `path_length_bars`, anchor mode, and genome component rows. Component rows include enabled state, component key, source column, encoding type, static bin configuration where used, `lookback_bars`, missing token, and display name. It supports AS9 MVP encodings `identity_numeric`, `categorical`, `boolean_symbolic`, `static_bin`, and `variation_direction`, calls `AnalysisSuiteGenomePathBuilder.validate_encoding_definition(...)`, and displays validation blockers, warnings, and errors. Genome encoding definitions remain in memory and are not persisted.

The same tab provides row-anchored and POI-family-anchored path previews. Row-anchored preview calls `AnalysisSuiteGenomePathBuilder.preview_paths(...)`. POI-family-anchored preview requires a current AS8 family preview report and calls `AnalysisSuiteGenomePathBuilder.preview_paths_for_poi_family(...)`; AS8 owns POI/family discovery and the GUI does not recompute POIs. Reports display status, row count, path count, sample paths, sample snapshots/components, blockers, warnings, and errors. Genome paths remain in memory and are not persisted.

The Analysis Suite GUI does not own readiness, preview, target, feature eligibility, leakage, diagnostic, POI/family, genome, or dataframe-read policy. Policy remains in `AnalysisSuiteDatasetReadinessService`, `AnalysisSuiteDataframePreviewService`, `AnalysisSuiteTargetPlanner`, `AnalysisSuiteFeatureSetPlanner`, `AnalysisSuiteDiagnosticReportService`, `AnalysisSuitePoiFamilyPlanner`, and `AnalysisSuiteGenomePathBuilder`; the GUI must not inspect `manifest.json`, `dataframe.csv`, or `source_ohlcv.snapshot` to classify readiness, feature/leakage, POI/family, or genome policy, and it must not load `dataframe.csv` directly or call `AnalysisDatabaseStore.load_dataframe(...)`. Previewable does not mean analysis-ready: non-strict datasets may be previewed only when AS1 allows it, with warnings and blockers still visible.

Selection changes clear stale state: changing the selected Analysis Database clears target, feature, diagnostic, POI, family, and genome previews; changing target settings clears downstream feature and diagnostic state; changing feature selections clears diagnostic and POI/family/genome state; changing POI definition inputs clears stale occurrence/family/genome reports; changing family condition inputs clears stale family/genome reports; and changing genome encoding inputs clears stale genome path reports. Initial manual GUI exploration after AS-GUI-1 found that workflow acceptable for continued work. Layout and small usability polish remain future work and are not considered complete.

Still out of scope for the GUI: AS10 controls, category-builder controls, white-box rule discovery, rule mining, model training, signal generation, backtesting, target/label/feature-set/diagnostic-report/POI/family/genome persistence, POI/family stores, genome stores, `FeatureSetStore`, Analysis Projects, Analysis Runs, Analysis Reports, trading workflows, road classification, outcome distribution analysis, Dynamic Binner fitting, full Dynamic Binner, full Variation Analyzer, artifact calculation, recipe execution, Analysis Database build/rebuild/materialization, component editing, database extension, raw OHLCV repair/validation, manifest writes, dataframe writes, and GUI-owned leakage, feature-eligibility, source-eligibility, POI/family validation, or genome validation policy.

After AS10-AUDIT, the next Analysis Suite implementation step is expected to be backend-only AS10 rule testing; AS10 GUI controls remain future work. GUI polish may be handled separately if manual exploration finds usability issues. Future Analysis Suite GUI work should keep backend services as the policy owners; GUI code must not infer feature eligibility from raw CSV headers, compute labels, compute POI occurrences or family memberships, compute genome snapshots or paths, compute variation descriptors, fit bins, compute white-box rule metrics, duplicate leakage/source/condition/genome/rule policy, load `dataframe.csv` directly, write manifests/dataframes, persist definitions/reports, or perform Data Manager mutation.

Current Analysis Database UI behavior:

- dataset selection lists only `ok` and `modified` OHLCV datasets from the CoreBridge/data-layer loadable catalog;
- modified datasets are labeled with `(Modified)`;
- when no loadable OHLCV exists, the selector shows `No validated OHLCV datasets available` guidance pointing to Historical -> OHLCV Maintenance;
- OHLCV preview checks loadability through CoreBridge and uses the data-layer `csv_path` from the loadability report before bounded read-only preview;
- the database-name field is prefilled with the selected dataset prefix, for example `BTCUSDT_30m_`;
- database names must not contain spaces or other whitespace;
- duplicate visible database names are rejected for the same market/timeframe partition during draft creation and rename;
- saved artifact rows use checkboxes for selection; highlighting is focus/preview only;
- checked saved artifact columns feed the `Database seed creator` only;
- `Database seed creator` is the only user-facing Analysis Database creation path; it creates a draft `manifest.json` from checked artifact columns and does not materialize `dataframe.csv`;
- `Database Builder` rows include checkboxes, and selected-database actions are enabled only when exactly one database is checked;
- `Build Selected Database` is enabled for draft/unmaterialized databases and opens a dedicated build dialog;
- the build dialog auto-loads saved indicators, oscillators, and constructs for the selected market, highlights already-present database components for review, and materializes `dataframe.csv` from the existing manifest recipe without changing components;
- `Rebuild Selected Database` is enabled for materialized databases and rewrites `dataframe.csv` from the same saved manifest recipe;
- build/rebuild preserves the same `database_id`, folder, display name, feature sources, feature columns, and recipe hash while updating materialization metadata;
- build/rebuild does not add, remove, or replace artifact components and does not run duplicate visible-name validation as if a new database were being created;
- `Edit Selected Database Components...` opens a dedicated component editor, auto-loads saved artifacts for the selected market, highlights already-present Saved Artifact Columns with light green `#C8F7C5` background, black foreground, and bold font, and supports explicit add/remove/replace actions;
- saving component changes intentionally changes the manifest recipe, resets materialization to draft, removes stale `dataframe.csv` when present, and requires a later build;
- `Extend Database from Collection...` opens from the selected Analysis Database workflow, requires an existing selected database, and displays C2 resolved components, blockers, warnings, duplicate columns, and geography reports before any mutation;
- recipe collection database extension appends resolved components only through `RecipeCollectionDatabaseService.extend_database_from_plan(...)` after `Confirm Database Extension`;
- the GUI no longer offers collection-driven database creation; the retained backend create method remains a data-layer compatibility contract;
- missing, stale, source-drifted, freshness-unknown, blocked, duplicate-column, and cross-market collection artifacts remain visible as blocked plan items and are not silently included;
- Saved Indicators / Oscillators / Constructs exposes `Select All`, `Deselect All`, `Check Update`, and `Update Selected Artifacts` for checked saved artifact rows;
- Database Builder exposes `Select All`, `Deselect All`, `Check Update`, and `Update Selected Databases` for checked Analysis Database rows;
- selected update `Check Update` displays service-produced OLD/CURRENT/UNKNOWN/BLOCKED/ERROR statuses for artifacts and OLD/CURRENT/DRAFT/UNKNOWN/BLOCKED/ERROR statuses for databases without mutating files;
- selected update execution acts only on checked OLD/actionable items from the latest plan; DRAFT databases are not OLD;
- rename and delete are exposed as user actions, but durable mutation is store-owned;
- Data Manager opens maximized and uses a compact layout where the top row contains Dataset and Calculate and Save Tool Outputs, the middle row contains DataFrame Preview and Saved Indicators / Oscillators / Constructs, and the lower area keeps Data Checks / Metadata Tools plus Database seed creator on the left with Database Builder on the right;
- main Data Manager widgets use the shared right-side `make_button_rack(...)` action layout with a 260px minimum action rack width;
- the artifact calculator popup opens at 60% of usable screen width and 60% of usable screen height while preserving its 900x620 minimum size so Calculate and Save Tool Outputs controls remain readable;
- the Data Manager-only `Construct Batch...` action appears when the Calculate and Save Tool Outputs family is Constructs; Research Suite Financial Tools windows do not expose this action;
- Saved Artifact Recipes, Saved Artifact Recipe Collections, Edit Analysis Database Components, and Extend Analysis Database from Collection dialogs open at 60% of usable screen width and are centered/fitted against available geometry while preserving their minimum sizes;
- DataFrame Preview keeps source, row-limit, and visible timestamp information in the content header while its action remains in the shared button rack;
- saved artifact actions use the shared button rack so the list retains content width;
- Database Builder gives the database list and manifest/details area equal display space;
- Data Manager-local text is enlarged and widget titles are bold while normal labels/buttons remain normal weight;
- Saved Artifact Recipes and Saved Recipe Collections dialogs use larger readable list areas so long names are visible.

Current artifact recipe / recovery UI behavior:

- saved artifact recipes are listed separately from saved artifact value files;
- highlighted recipe rows drive single-recipe actions such as load, calculate, and delete;
- checked recipe rows drive collection creation;
- saved recipe collections show ordered embedded recipe snapshots and optional `source_database_id` linkage;
- `Create Recipes from Study Environment...` lists saved Study Environments, supports important-only planning, displays planner-owned candidates/blockers/warnings, lets only exportable candidates be selected, and persists recipes or optional collections through the B2 service;
- `Check Recovery Status` displays planner-owned status for expected artifacts without executing anything;
- `Recover Actionable Artifacts` delegates regeneration to the recovery regenerator and executor, and only planner-actionable recipes are attempted;
- `Rebuild Linked Database` delegates linked Analysis Database materialization through the recovery database rebuilder and `AnalysisDatabaseStore`;
- `Plan Updates...` opens a recipe-collection update dialog backed by `DataManagerUpdateService`;
- the update dialog displays service-produced plan items, actions, blockers, warnings, and execution reports;
- update execution supports selected actions and all actionable actions, reports completed/skipped/failed/blocked results including partial failures, and refreshes saved artifact and Analysis Database lists after execution;
- Data Manager refreshes recipe, recipe collection, saved artifact, and database lists after successful persistence, recovery, rebuild, or selected-database collection updates where relevant.
- Dataframe materialization remains outside GUI ownership.

Current selected artifact/database update UI behavior:

- `DataManagerSelectedUpdateService` owns selected artifact and Analysis Database planning/execution truth;
- selected saved artifact planning covers checked indicators, oscillators, and constructs from the Saved Indicators / Oscillators / Constructs widget;
- selected Analysis Database planning covers checked Database Builder rows;
- `Check Update` is read-only and marks GUI rows from service-produced status/actionability only;
- `Update Selected Artifacts` regenerates only checked OLD/actionable saved artifacts from the latest plan through the selected-update service;
- `Update Selected Databases` rebuilds only checked OLD/actionable materialized Analysis Databases from the latest plan through the selected-update service;
- database update preserves `database_id`, folder identity, display name, manifest recipe, feature sources, feature columns, and component list;
- selected database update does not add, remove, replace, create, or rename Analysis Databases;
- stale source artifacts block database rebuild rather than being silently regenerated by the database update action;
- selected update dialogs provide preflight, synchronous running state, and terminal reports; OK is available only after terminal state;
- no fake mid-operation cancellation is offered for synchronous calculation or materialization;
- status markings are display state from the latest check and are not written into artifact or database metadata; refreshing lists may clear or refresh those markings.

Current Construct Batch Builder UI behavior:

- the workflow opens from Data Manager -> Calculate and Save Tool Outputs -> Constructs -> `Construct Batch...`;
- unary source expansion supports `derivative`, `angle`, `percent_span_angle`, and `angle_momentum`;
- binary delta expansion supports `delta` and reports direction as `delta = minuend - subtrahend`;
- generic batch mode does not offer `braids`, `braid_instability`, `trap_area`, or `dynamic_binning`; braids, braid instability, and trap area require curated topology templates, while dynamic binning is a grouped analysis workflow;
- supported source groups include all saved indicators, all saved oscillators, all saved constructs, delta fixed close, and saved artifact fixed sources for delta;
- cross-widget handoff for currently selected saved artifact columns is postponed until a clean selection bridge exists;
- `Preview Plan` calls the data-layer construct batch planner and writes nothing;
- the plan table shows planned, existing_recipe, blocked, and error items, including expected outputs and blocker/warning summaries;
- blocked and error plan items cannot be selected for persistence or calculation;
- planned items may be saved as recipes and existing_recipe items may be reused or included in collections;
- `Save Recipes` calls the construct batch persistence service to save selected planned recipes through `ArtifactRecipeStore` and reuse selected existing recipes;
- `Save as Collection` persists/reuses selected recipes first and saves an ordered recipe collection through `ArtifactRecipeCollectionStore`;
- `Calculate Artifacts` persists/reuses selected recipes first, then calls the construct batch execution service, which executes saved/reused recipes sequentially through `ArtifactRecipeExecutor` / `ArtifactCalculationService`;
- preflight, running, and terminal states report selected counts, saved/reused recipes, completed/skipped/blocked/failed calculation results, and partial failures without claiming background task execution;
- the dialog refreshes saved artifact lists after calculation and refreshes recipe/collection lists when persistence occurs where safe hooks exist;
- Construct Batch never extends, builds, rebuilds, creates, or materializes Analysis Databases automatically.

Research Suite artifact save also saves or reuses the corresponding reproducible recipe in the same Data Manager-visible `ArtifactRecipeStore(historical_root=...)` partition-local `artifact_recipes` store. Artifact sidecars record `recipe_id`, `recipe_hash`, and `recipe_hash_short` as recipe metadata.

Study application remains chart-local and non-persistent. Saving a Study Environment or Workspace Snapshot does not directly persist recipes.

Current OHLCV loadability behavior:

- only `ok` and `modified` OHLCV metadata statuses are selectable/usable;
- `unknown`, `not_validated`, `warning`, `error`, missing/unreadable metadata, metadata mismatch, missing CSV, and stale validation fingerprints are blocked;
- final data-layer paths still enforce the gate through `ArtifactCalculationService`, `AnalysisDatabaseStore`, and `ArtifactRecoveryPlanner`;
- GUI code displays catalog results and messages only; it does not parse `candles.meta.json`, parse `candles.csv`, or implement validation/loadability rules.

It must not:

- create chart-local studies;
- apply financial tools to panes;
- own pane/render state;
- own financial-tool compute semantics;
- invent persistence semantics;
- manually rewrite Analysis Database manifests or move/delete database folders;
- silently mutate valid artifact metadata;
- classify artifact recovery state locally;
- classify selected update state locally;
- classify Construct Batch source eligibility, alignment, or existing-recipe truth locally;
- classify dataset geography locally;
- map recipe collection snapshots to Analysis Database components locally;
- classify OHLCV loadability locally;
- parse or compare `source_ohlcv.snapshot` locally;
- regenerate artifacts without the data-layer recovery/executor boundary;
- rebuild linked Analysis Databases outside `ArtifactRecoveryDatabaseRebuilder` / `AnalysisDatabaseStore`;
- rebuild selected Analysis Databases outside `DataManagerSelectedUpdateService`;
- execute Construct Batch recipes outside `DataManagerConstructBatchExecutionService`;
- consume checked artifact columns inside Database Builder;
- replace Analysis Database components during build/rebuild;
- execute Plan Updates from the recipe collection database create/extend dialog.

Data Manager maintenance actions such as metadata backfill are restore-only operations. They may recreate missing or unreadable `.meta.json` sidecars from existing CSV files, but they must not rewrite CSV data and must not be treated as the normal save path. Analysis Database create, rename, delete, build, rebuild, and explicit component-edit operations must go through the appropriate data-layer service, because `manifest.json` is the metadata-sidecar equivalent for the folder-backed `dataframe.csv` artifact. GUI release checks enforce that Database Builder does not consume artifact selections, does not call feature-replacement rebuild APIs, keeps build/rebuild separate and manifest-driven, and keeps main Data Manager actions in the shared right-side button rack layout.

Data Manager lineage hardening, source-drift classification, and update planning are data-layer owned. Generated derived artifact sidecars and Analysis Database materialization metadata receive `source_ohlcv.snapshot` through the save/materialization services, including source validation, fingerprint, and source-correction provenance when applicable. `ArtifactRecoveryPlanner`, `AnalysisDatabaseStore`, `DataManagerUpdateService`, and `DataManagerSelectedUpdateService` may report source-drift and update-plan status to GUI recovery/update views, but the GUI does not parse, create, display, compare, or classify this snapshot.

The implemented update UI covers recipe-collection scoped plans plus explicit selected saved artifact and selected Analysis Database plans. These workflows follow local Data Manager data-layer service patterns rather than adding CoreBridge update-plan APIs. They are not a dataset-wide Update Manager dashboard, arbitrary dependency graph workflow, or background task/progress monitor.

Construct Batch Builder follows the same local Data Manager service boundary. The GUI collects batch intent, displays planner/persistence/execution reports, and requests list refreshes. `DataManagerConstructBatchPlanner` owns source eligibility, timestamp-safe alignment, expected recipe preview, and read-only existing-recipe detection. `DataManagerConstructBatchPersistenceService` owns recipe and collection persistence. `DataManagerConstructBatchExecutionService` owns persistence-before-calculation orchestration and delegates artifact calculation to the existing recipe executor/calculation services. The GUI must not parse sidecars for policy, prove alignment from row counts, directly write artifact files, or call artifact calculation internals.

Study Environment recipe export and selected-database collection extension are also local Data Manager workflows that display data-layer plans and reports.

Study Environment recipe export and selected-database collection extension do not calculate artifacts, execute recipes, run update plans, export Workspace Snapshots, offer collection-driven database creation, or materialize databases.


## Historical Workspace Model

Historical chart sessions are hosted by `HistoricalDataManagerWindow`.

The New Historical Chart selection dialog consumes CoreBridge/HistoricalDatasetService loadable catalog surfaces for exchange, market type, symbol, and timeframe discovery. It shows only accepted `ok` and `modified` OHLCV datasets, labels modified datasets, and displays OHLCV Maintenance guidance when no validated datasets are available. It must not walk `data/historical` directly or validate datasets by guessing filesystem contents. The accepted dataset value artifact remains strict `ohlcv/candles.csv`, and `HistoricalDatasetService.open_dataset(...)` enforces the final load gate before chart loading.

Any historical dataset refresh/cache-invalidation action exposed by the GUI must request Core-owned historical dataset cache invalidation through CoreBridge. It is a cache-refresh intent, not a chart-session reload and not a filesystem mutation path.

The embedded historical workspace manages:

- up to 8 embedded historical chart panels;
- 8 stable logical slots ordered as `1-2`, `3-4`, `5-6`, `7-8`;
- panel embedding, detaching, docking, and closing;
- chart-level Position controls for moving a chart to another slot or swapping with an occupied slot;
- two visualization modes: `Scroll 4` and `Fit 8`;
- adaptive visual layout based on the number of currently embedded charts.

Each chart session is represented by `HistoricalChartPanel`.

### Embedded mode

Created via:

`File → New Chart`

Logical slot rules:

- each embedded chart occupies one logical slot from 1 to 8;
- new charts use the first available non-reserved slot;
- detached charts reserve their original slot while floating;
- docked charts return to their reserved original slot;
- reserved detached slots are protected from new charts and position moves;
- chart Position controls preserve slot identity and may swap charts when the target slot is occupied.

The logical slot order remains:

```text
1 | 2
3 | 4
5 | 6
7 | 8
```

### Visualization modes

`Scroll 4` keeps the workspace vertically scrollable so larger layouts can extend below the initially visible area.

`Fit 8` fits the current embedded chart layout into the usable workspace area without vertical scrolling.

Both modes preserve the same logical slot order and chart-session identity.

The mode selector is exposed through the `Window` menu as checkable `Scroll 4` / `Fit 8` actions. The top-right menu-bar mode label displays the current mode and updates when the mode changes. This is shell UI only; mode state remains owned by `HistoricalWorkspaceWidget`.

`HistoricalDataManagerWindow` opens maximized by default. This is window presentation only and does not change chart-session, workspace, dataset, or renderer ownership.

### Pan Anchor

`Pan Anchor` is a checkable quick-action button in the Research Suite menu-bar corner. It is off by default.

When enabled, a user horizontal pan in any active historical chart recenters the other eligible charts in the same Research Suite around the source chart's current center timestamp. The target charts keep their own zoom/visible width and vertical y-range/autoscale state.

Pan Anchor rules:

- synchronization is horizontal-only;
- synchronization is timestamp-center based, not raw pixel or raw bar-index based;
- embedded charts and detached charts still tracked by the same Research Suite are eligible;
- charts in other Research Suite windows are not targeted;
- zoom, autoscale/manual-y, studies, notebook markers, and renderer state are not synchronized;
- programmatic navigation such as Notebook/POI/Potential Trades Go or Workspace Snapshot load does not become a pan-sync source;
- Research Suite owns reentry protection so target recentering does not loop back into the source chart.

### Compact chart-area layout

The historical workspace uses compact chart-area margins and grid spacing to reserve more screen space for data. Pane separation should come from subtle pane/splitter borders and splitter handles rather than large dead gaps. Render surfaces use reduced plot padding while preserving readable right-axis and time-axis labels.

Historical chart-space domain padding remains unchanged. The `1000 / 1000` left/right domain padding is chart behavior owned by workspace/controller/refill contracts, not cosmetic spacing.

### Adaptive visual layout

The visual layout is compacted from the currently embedded charts in logical slot order. Empty or reserved detached slots do not force blank visual holes, but their logical slot identity remains preserved for dock-back and position controls.

Layout rules:

- 1 chart → one full-widget chart;
- 2 charts → one row with two equal columns;
- 3 charts → one full-width chart above two equal-width charts;
- 4 charts → 2x2;
- 5 charts → 2x2 plus one full-width bottom chart;
- 6 charts → 3x2;
- 7 charts → 3x2 plus one full-width bottom chart;
- 8 charts → 4x2.

Odd chart counts always include one full-width chart. For 3 charts the full-width chart is on top; for 5 and 7 charts the full-width chart is at the bottom. The 1-chart case fills both width and height.

### Floating mode

Panels can detach into `HistoricalChartWindow` and dock back without losing chart-session state.

The same `HistoricalChartPanel` instance is preserved across embed/detach/dock flows. Floating mode is a shell change, not a second chart-session owner. Dock-back restores the panel to its preserved logical slot when that slot is available.

### Notebook

The Research Suite window (`HistoricalDataManagerWindow` internally) owns the Notebook user workflow for chart analysis notes and runtime notebook annotations.

Notebook responsibilities are split deliberately:

- `HistoricalNotebookWindow` is a GUI-owned in-memory editor. It displays and edits notebook content, emits user intents, and does not own durable persistence.
- The Research Suite window owns the `Notes` menu actions, coordinates `HistoricalNotebookStore`, resolves notebook `Go` requests to active chart panels, applies runtime POI/Potential Trade markers to matching charts, and routes save/update requests through the store boundary.
- `HistoricalNotebookStore` owns durable notebook JSON files under `chart_presets/notebooks` and must remain free of GUI / PySide imports.
- `HistoricalWorkspaceSnapshotStore` stores only an optional `notebook_ref` with notebook identity/display metadata. It does not embed notebook content.
- Notebook Manager owns assignment/unassignment UX, assignment summaries, notebook deletion, and cleanup of referencing `notebook_ref` values when an assigned notebook is deleted.

Notebook chart entries are keyed by dataset identity (`exchange`, `market_type`, `symbol`, `timeframe`). Chart position may be shown as `last_seen_position`, but it must not participate in notebook identity.

Notebook tabs contain structured `Notes`, `Potential Trades`, and `Point of Interest` sections:

- Notes rows expose `Delete | Date / Time | Note` and do not navigate charts;
- Potential Trades rows expose `Go | Delete | Date / Time | Direction | Starting Price | Target % Movement | Closing Price | Outcome | Note`;
- Potential Trades direction is empty by default and must be explicitly set to `Long` or `Short` before a chart marker is projected;
- Point of Interest rows expose `Go | Delete | Date / Time | Title | Description`;
- row deletion always asks for confirmation;
- Date / Time double-click navigation is disabled, so explicit Go buttons are the only notebook navigation path.

Notebook free-text fields support basic rich-text formatting:

- compact formatting palettes sit beside Add Note, Add Trade, and Add Point of Interest;
- supported controls are bold, underline, text color, bullet list, and numbered list;
- formatting applies to notebook description, note text, trade note text, POI title, and POI description;
- IDs, timestamps, dates, numeric fields, dataset identity, symbol/timeframe fields, and direction/outcome selectors remain plain fields.

Potential Trades and POI `Go` buttons emit `goto_requested(chart_key, ts_ms)`. The notebook window does not move charts directly. `HistoricalDataManagerWindow` performs active-chart lookup and delegates chart centering through `HistoricalChartPanel` and `HistoricalChartController`.

POI rows and eligible Potential Trades rows may be projected onto matching active charts as runtime annotation markers. These markers are notebook-driven chart annotations:

- they are not financial tools;
- they are not hidden studies;
- they do not enter `ChartStudyRegistry`;
- they are not saved as Study Environment content;
- POI markers are derived from notebook POI rows at runtime;
- Potential Trade markers are derived from Potential Trades rows with valid Long/Short direction at runtime;
- Long Potential Trade markers render as green upward arrows below the bar;
- Short Potential Trade markers render as red downward arrows above the bar.

Notebook JSON may include additive `annotation_settings` for `poi_marker_offset`, `pt_long_marker_offset`, and `pt_short_marker_offset`. Existing notebooks without these values load with defaults, and legacy `pt_marker_offset` is only a compatibility fallback. These settings are notebook annotation state, not Study Environment state and not Workspace Snapshot assignment truth.

The menu-bar corner quick actions include an optional `Notebook` button before the Study Environment buttons. It opens the notebook assigned to the current workspace snapshot when a valid `notebook_ref` is available. Notebook assignment/unassignment emits a narrow refresh path so the visible notebook indicator updates immediately for the current workspace snapshot without reloading the workspace.

Notebook save supports explicit Save as new and Update existing modes. Update existing uses `HistoricalNotebookStore.update_notebook(...)` to preserve `notebook_id` and `created_at_ms`, advance `updated_at_ms`, recompute `content_hash`, and atomically overwrite through the store. Save as new creates a distinct notebook identity and does not repoint existing Workspace Snapshot `notebook_ref` values. Create New Notebook clears prior loaded identity before refreshing workspace charts.

Dirty-state protection is editor-owned. The notebook editor tracks edits to name, description, table cells, combo cells, row add/delete actions, chart tab deletion, annotation offsets, and chart refresh payload changes. Dirty notebooks prompt with Save / Don't Save / Cancel before close, Create New Notebook, Load Notebook, assigned notebook replacement, or Workspace Snapshot assigned-notebook replacement. Save proceeds only after the existing save flow succeeds; Don't Save continues without writing; Cancel aborts the close/load/replace action.

Notebook persistence preserves plain-text compatibility. Free-text values remain populated in the existing plain fields, while formatted content may be stored in optional parallel HTML fields such as `description_html`, `note_html`, and `title_html`. Old plain-text notebooks load without a separate upgrade step, and `content_hash` includes formatted HTML fields when present.

### Saved Study Environment and Workspace Snapshot save/update/delete/management

The Study Environment and Workspace Snapshot save dialogs support Save as new and Update existing modes. Save as new remains the default.

Rules:

- update mode requires selecting an existing saved item;
- selecting an existing item preloads its name and description;
- updating a Study Environment reuses the selected internal `setup_id` and does not create a duplicate setup file;
- updating a Workspace Snapshot reuses the selected `snapshot_id`, does not create a duplicate snapshot file, and preserves notebook reference behavior;
- GUI dialogs collect save intent and display fields only; stores own identity preservation, timestamps, hashes, duplicate checks, and atomic writes.

The Study Environment and Workspace Snapshot load dialogs expose confirmed Delete actions.

Rules:

- loading a Workspace Snapshot first shows a preflight dialog with snapshot name, description, chart count, chart recap, notebook assignment, and a warning that current workspace content will be replaced or added to;
- preflight Cancel aborts before restore;
- confirmed load switches to an indeterminate loading state during the existing synchronous GUI-thread restore;
- restore does not offer mid-restore cancellation, and failure is reported cleanly;
- the restore path is not transactional if a later chart restore fails after partial UI mutation;
- deleting a saved Study Environment uses `ChartStudySetupStore.delete_setup(setup_id)` and does not remove currently applied chart studies;
- deleting a Workspace Snapshot uses `HistoricalWorkspaceSnapshotStore.delete_snapshot(snapshot_id)` and does not delete referenced notebooks, datasets, saved Study Environments, or saved artifacts;
- when a snapshot references a notebook, the delete confirmation states that the notebook will not be deleted;
- dialogs refresh their lists and clear stale selection/details after successful deletion.

The Research Suite exposes `Manage Study Environments...` and `Manage Workspace Snapshots...`.

`StudyEnvironmentManagerDialog` lists saved Study Environments, displays environment details and contained studies, edits top-level name/description, edits per-study serialized `user_metadata` (`important`, `dataset_role`, `description`), preserves study params/style/bindings, and deletes through `ChartStudySetupStore` APIs. It does not create recipes or calculate artifacts.

Save Study Environment / Update existing Study Environment includes a compact per-study metadata editor for the studies being saved. The dialog lets the user set Important, Dataset role, and Description before persistence. These choices are written into cloned serialized study payloads for the saved Study Environment; they do not mutate the live chart registry. After save, the Study Environment Manager remains the editor for saved metadata.

`WorkspaceSnapshotManagerDialog` lists saved Workspace Snapshots, displays snapshot details, saved charts and studies, and `notebook_ref`, edits top-level name/description, and deletes through `HistoricalWorkspaceSnapshotStore` APIs. Embedded snapshot study metadata is read-only in RS4.

No assigned-notebook deletion, recipe export, artifact calculation, or Analysis Database creation is part of this dialog.

---

## HistoricalChartPanel

`HistoricalChartPanel` is the chart-session unit.

It owns:

- `ChartWorkspaceWidget`
- `HistoricalChartController`
- `ChartStudyRegistry`
- dataset identity for the open session
- financial tool entrypoint
- chart-local study lifecycle
- chart-local study style persistence
- style reapply without recomputation
- chart-local oscillator visual policy seeding
- chart-local segmented visual derivation for historical conditional studies such as HCK
- chart-local grouped marker-spacing controls for event-style studies such as `peaks_troughs`
- translation from controller projections back onto chart-local study ids
- chart-local render-key namespacing for duplicate same-config studies

It is:

- reusable
- shell-agnostic
- the owner of chart-local study truth for the current session

Important rule:

The panel owns chart-local study identity and visual state, including duplicate-instance disambiguation over shared controller projection truth. It does not own full-dataset truth, persistence semantics, pane layout ownership, or renderer semantics.

---

## Historical Ownership Chain

The historical chart stack follows this ownership chain:

`Core dataset truth → controller/session truth → panel chart-local study truth → workspace pane/layout contracts → pane handoff → renderer execution`

This is the central GUI rule for the chart engine.

It means:

- the dataset is not owned by the viewport
- the viewport is not owned by the renderer
- studies do not own pane layout
- workspaces do not own full-study computation truth
- panes do not become durable state authorities
- renderers do not invent chart semantics or hidden ownership

The chart is a stable environment.
The camera moves across it.
The studies live on it.
The renderer draws it.

---

## Chart Session Data Model

The historical chart engine uses a resident-slice model with a global-index viewport camera.

Important distinction:

- viewport navigation uses global chart-space indices
- render surfaces consume resident-local arrays only

This is the enforced contract.

The controller may compute against the full historical dataset, but render payloads sent to the chart layer must already be trimmed to the current resident slice.

That means:

- computation scope may be full-dataset
- persistence scope may be full-dataset
- rendering scope is resident-local only

Renderers must not reinterpret full-dataset indexing.

### Controller/session truth

Controller-owned chart-session truth includes:

- canonical dataset identity
- canonical timeline
- cached full-dataset dataframe
- resident slice base index
- resident candle payload
- dataset edge availability flags
- full-dataset study truth
- current resident-local projected study payloads

This is the historical truth that the GUI works from.

---

## Chart Space vs Viewport Camera

Historical chart behavior depends on a strict separation between chart space and camera state.

### Dataset space

Dataset space is the canonical candle range:

`0 .. dataset_count - 1`

Only those indices correspond to real candles.

### Historical chart space

Historical chart space is a fixed environment over which the viewport camera moves.

For historical sessions, workspace defines explicit domain padding:

- left padding: `1000`
- right padding: `1000`

So the historical chart environment is effectively:

`[-1000, dataset_count + 1000)`

Those padded slots are legal camera space, but they are not candle truth.

### Viewport contract

`ChartViewport` owns the shared horizontal camera only.

It owns:

- current visible horizontal window
- min/max visible bars
- current crosshair index
- x-index ↔ pixel mapping
- horizontal zoom behavior inside the supplied chart-space domain
- domain clamping inside the chart-space environment supplied by workspace

It does **not** own:

- dataset truth
- resident-slice truth
- refill policy
- pane layout
- renderer semantics

### Autoscale / zoom rule

User-facing Autoscale belongs to the workspace-owned price-pane vertical fit contract, not to viewport ownership.

The viewport may still expose legacy compatibility entry points that use older "anchor zoom" naming, but that naming is not the architectural source of autoscale semantics.

Horizontal zoom must never:

- redefine chart-space boundaries
- redefine historical domain padding
- force a permanent right-edge ownership rule
- change who owns resident truth

Initial latest-edge placement is allowed on first historical load. After that, the chart remains a stable padded environment and the user may pan independently across it.

---

## HistoricalChartController

`HistoricalChartController` is the compute/render boundary for historical chart sessions.

It coordinates:

- dataset opening
- historical slice requests
- financial tool apply
- financial tool save
- controller-owned study projection refresh

### Controller responsibilities

The controller owns:

- canonical timeline for the open chart session
- canonical full-dataset dataframe cache
- GUI-thread marshalling and stale-result guards for dataset-open and slice callbacks
- resident slice truth
- refill pressure evaluation
- normalization of padded camera space back into dataset-interest windows
- full-dataset study truth
- resident-local study projection
- renderable-signal filtering
- preservation of non-renderable `analysis_usable` full-dataset outputs for temporary construct chaining without rendering them

### Compute/render contract

For apply:

- compute may run on the full canonical dataset
- construct sources must be aligned deterministically
- only outputs declared renderable may become chart series
- chart-renderable payloads with zero renderable outputs fail unless the tool explicitly declares `accepts_empty_render_output`
- emitted series are trimmed to the active resident slice before they become chart series

For save:

- compute runs on the full canonical dataset
- full-dataset result is persisted without render trimming


### UTC historical dependency injection

When `Universal Trend Classifier` is applied or saved in a historical chart, the controller must prepare the dataframe before calling the financial-tool runtime:

1. load the full canonical OHLCV dataframe;
2. resolve the directional trend dependency from `trend_fractal_window` (falling back to legacy `fractal_window`) and optional `trend_peak_column` / `trend_trough_column`;
3. resolve the horizontal range dependency from `range_fractal_window` and optional `range_peak_column` / `range_trough_column`;
4. locate the saved `peaks_troughs` indicator artifact for the same exchange, market type, symbol, and timeframe;
5. inject all unique selected `peak_fractal_N` / `trough_fractal_N` columns through deterministic timestamp alignment;
6. call UTC with `ToolExecutionContext(environment="historical")`.

This is a controller/source-resolution responsibility. Trend and range dependencies are separate logical requests even if they are satisfied from the same saved artifact. UTC remains compute-only. Renderers, panes, and workspace must not load Peaks & Troughs artifacts or infer trend semantics.

The Financial Tool Manager should expose UTC fractal selection as user-facing dropdowns for `Up/Down Trend Fractal` and `Range Trend Fractal` over the Peaks & Troughs windows `3`, `5`, `7`, `9`, and `11`, plus `Range Break Mode` (`close`, `wick`, `hybrid`). Raw peak/trough column overrides are advanced compatibility parameters, not the normal user path.

The controller must preserve the shared-extreme UTC semantics delivered by the runtime: an uptrend may end at the same peak where a downtrend starts, and a downtrend may end at the same trough where an uptrend starts. Only one shared boundary bar is allowed; multi-bar uptrend/downtrend overlap is invalid. Invalid OHLC/source rows are hard continuity breaks; UTC directional intervals must not bridge NaN or malformed candle/source gaps.

### Historical refill rule

Viewport changes are camera-change inputs only.
Refill policy remains controller-owned.

For historical sessions the controller:

- evaluates refill pressure against the current resident window
- normalizes padded camera space back into canonical dataset windows
- issues slice requests through the dataset service
- rejects stale returned slices that no longer cover the current camera-interest window

This prevents an old slice from overwriting newer resident truth after the camera has already moved elsewhere.

---

## ChartModel

`ChartModel` is the GUI-side chart data container.

It owns:

- canonical base OHLC layer currently resident in the GUI process
- auxiliary base volume layer
- resident base index used for local/global alignment
- derived overlay render state
- derived oscillator render state
- trade annotations

Canonical rule:

- OHLC bars are the base chart layer
- volume is auxiliary base data
- overlays and oscillators are derived render state
- studies do not replace or redefine the base chart layer

### Batched change emission

`ChartModel` supports batched change emission.

This allows workspace to group large resident-slice or multi-study updates into one coherent change rather than emitting repaint-triggering changes for every individual mutation.

The model is a transport and state container. It is not a styling authority and not a refresh coordinator.

---

## Chart Workspace Architecture

`ChartWorkspaceWidget` owns:

- `ChartModel`
- `ChartViewport`
- `Crosshair`
- pane stack
- pane lifecycle
- pane ordering
- managed overlay-study grouping
- oscillator pane registry and ordering
- study-to-pane mapping
- pane view state
- pane visual policy state
- price-pane y-range / autoscale contract
- historical chart-space domain policy
- explicit payload push into panes
- batched projected-study application

Current pane structure:

- `PricePane`
- `VolumePane`
- `OscillatorPane(s)`

All panes share:

- viewport
- crosshair

### Pane ownership rules

Layout is owned by workspace, never by studies.

Workspace owns:

- pane registry
- pane ordering
- study-to-pane mapping
- overlay study grouping
- pane view state
- pane visual policy state
- price-pane y-range and pane-local vertical contracts
- explicit renderer-facing payload contracts

Rules:

- 1 oscillator study → 1 pane
- 1 study → N series
- 1 overlay study → 1 logical overlay entry
- 1 overlay study → N render series

### Historical domain policy

Workspace sets the chart-space domain policy appropriate to the mode:

- historical slices → fixed left/right historical padding
- snapshot/realtime flows → no historical padding by default

The viewport consumes that policy. It does not invent it.

### Autoscale contract

The user-facing Autoscale toggle is the workspace-owned price-pane vertical fit contract.

With Autoscale on, workspace resolves the price y-range from the current visible x-window using visible OHLC plus visible price-pane overlays.

For marker-style price overlays, the workspace-owned autoscale path must also reserve visual headroom for marker size and marker offset so event markers remain visibly fitted instead of clipping at candle highs/lows.

With Autoscale off, manual y-range becomes user-owned.

The viewport remains the shared horizontal camera in both cases.

---

## Pane Contract

Panes are the handoff boundary between workspace-owned state and render surfaces.

That means panes consume:

- workspace-owned pane view state
- explicit render payloads
- explicit pane visual policy
- shared viewport and crosshair

Panes do **not** own:

- full-study truth
- durable pane grouping policy
- workspace refresh orchestration
- semantic defaults

### PricePane

`PricePane` is the handoff boundary for:

- resident-local candles
- overlay series payload
- overlay fill payload
- workspace-owned price-pane view state
- workspace-owned price-pane y-range contract

### OscillatorPane

`OscillatorPane` is the handoff boundary for:

- oscillator series payload
- pane visual policy
- workspace-owned oscillator pane view state
- workspace-owned oscillator y-range contract

### VolumePane

`VolumePane` renders auxiliary base volume data against the same shared x-axis without becoming a second chart foundation.

Contract rules:

- workspace owns viewport-driven refresh reconciliation; the volume surface must not subscribe directly to `viewport_changed`;
- the pane is the handoff boundary and pushes one coherent payload into `VolumeRenderSurface.apply_contract(...)`;
- paint-local caching in the volume surface is allowed as an execution detail, but it must not introduce durable state ownership.

---

## Rendering and Refresh Model

Rendering is behavior-driven and contract-driven.

The panel resolves:

- pane target
- chart-local study identity
- duplicate-study chart-local render identity
- final chart-local style state
- pane-local oscillator policy seeding

The workspace resolves:

- pane ownership
- pane contracts
- explicit render payloads
- coherent batched application into panes and the chart model

The renderer executes that final state.

### Historical slice refresh path

Historical slice refresh follows this order:

1. controller applies the new resident candle slice
2. controller rebuilds resident-local study projections from full-study truth
3. panel maps those projections back onto chart-local study ids
4. panel resolves final styled resident-local payloads once
5. workspace reapplies that final payload once in a batched update
6. panes receive one coherent handoff
7. renderers draw from the final resident-local state

This avoids redraw churn caused by multi-pass reapply paths.

### Viewport refresh ownership

Viewport movement is a **camera-only** change, but it still changes which resident-local values are visible.
Leonardo therefore enforces a single refresh ownership rule:

- **Workspace** is the only owner of viewport-driven contract reconciliation.
- **Panes** are the handoff boundary: they receive explicit contracts from workspace and forward one coherent contract to render surfaces.
- **Render surfaces** repaint based on the final pane-owned contract and crosshair changes. They must not become secondary viewport-refresh coordinators.

Current implementation notes (v3.9):

- No render surface subscribes directly to `viewport_changed`. Only `HistoricalChartController` and `ChartWorkspaceWidget` observe camera movement.
- Workspace reconciles pane contracts on viewport changes and pushes one-shot contracts through panes into render surfaces:
  - `ChartRenderSurface.apply_contract(...)`
  - `VolumeRenderSurface.apply_contract(...)`
  - `OscillatorRenderSurface.apply_contract(...)`
- Render surfaces are contract-only consumers. Legacy setter-style update paths are not part of the supported architecture.
- Price/volume/oscillator surfaces may use static-scene caching (with crosshair painted as a dynamic overlay) to keep mouse-move cost low; static scene rebuild may be coalesced to avoid repaint storms on multi-chart apply.
- Style edits (e.g., series color/width/visibility) must invalidate any static-scene caches so the next repaint uses the updated chart-local style. Style changes must not require a visibility toggle to become visible.
- Cache invalidation must flow through public workspace/pane/surface contracts; the panel must not reach into renderer private cache fields.
- Overlay cards update from crosshair changes and explicit payload versioning. Managed overlays consume pane payload as the single source of truth.
- Renderers may keep paint-local caches for derived draw helpers (e.g., time-axis ticks) as long as they do not become durable state owners.

### Performance rule

Panning should behave like moving a camera over already-existing resident-local data.

That means:

- indicators are not recomputed during normal pan/zoom
- workspace must not reapply the same study in multiple passes for one refresh
- the model must emit one coherent change for a batched update when possible
- panes must not act like second refresh owners
- renderers must draw from the final payload they are given
- viewport movement must trigger **one** coherent contract refresh path (workspace), not many independent repaints across panes/surfaces
- overlay-card UI must not perform layout thrash on pan/zoom; it should update on crosshair/index changes instead
- pane-to-surface updates should be applied as one coherent contract to avoid repaint storms during slice refresh and multi-study reapply

### Resident target

Historical resident-window policy is intentionally larger than the visible window so normal horizontal movement can remain smooth without constant refills.

The current validated direction uses a `5000` bar resident target together with controller-owned refill policy.

---

## Price-Pane Rendering

Price-pane rendering uses:

- resident-local candles
- resident-local overlay series
- overlay fills resolved from chart-local study state
- marker-style overlay series for event studies
- workspace-owned y-range contract

Current price-pane study examples include:

- `BB` → `bb_middle`, `bb_upper_band`, `bb_lower_band`
- `HCK` → `fast_vwap`, `slow_vwap`
- `peaks_troughs` → `peak_fractal_3/5/7/9/11` and `trough_fractal_3/5/7/9/11`

`HCK` also emits `vwap_color`, but that output is non-renderable utility state and must not become a chart line.

Validated `peaks_troughs` rendering notes:

- it is a price-pane indicator-family study with sparse confirmed event outputs
- peaks render as downward markers above the bar
- troughs render as upward markers below the bar
- marker text identifies the fractal length
- default chart-local visibility starts with the 3-bar peak/trough pair only
- chart-local grouped `Above` / `Below` style edits fan out into the per-signal marker offsets for all peak or trough signals respectively

Overlay rendering rules:

- overlays are rendered only from resident-local series
- event-style studies may render through marker-capable overlay series rather than connected-line semantics
- fill descriptors are built deterministically from study-owned signal mappings
- conditional coloring remains visual-only
- historical segmented conditional studies such as HCK are resolved upstream by panel/resolver into explicit renderer-facing segmented payloads
- crossover continuity for segmented conditional studies is achieved by payload construction upstream, not by renderer-side semantic inference
- no renderer-side recomputation is allowed
- no renderer-side discovery of study grouping is allowed

Managed overlay-study grouping belongs to workspace, not to the renderer.

---

## Oscillator Visual Model

Oscillator visualization follows strict separation.

Visual policy flow:

- `HistoricalChartPanel` seeds defaults and pane policy
- `ChartWorkspaceWidget` persists pane policy state
- `OscillatorPane` owns pane behavior handoff
- `OscillatorRenderSurface` renders policy

Policy is:

- chart-local
- pane-scoped
- persisted
- visual-only

### Oscillator families

- single-line bounded: RSI, MFI
- two-line bounded: ARSI main line plus ARSI signal/mean line
- multi-line bounded: TDI RSI
- multi-line signal: SMI
- unbounded: OBV
- histogram + line: Volume and `volume_mean_{period}`

Current oscillator style/policy notes:

- ARSI uses dedicated `80 / 50 / 20` guide levels; RSI and MFI use `70 / 50 / 30`.
- Dynamic oscillator output names resolve to canonical chart-local defaults before style state is persisted.
- Threshold-aware line coloring splits at actual threshold crossings and leaves neutral regions controlled by the user-selected line style.

### Bounded oscillator behavior

Bounded oscillators may use:

- fixed bounds
- pane-local vertical drag
- guide levels
- threshold-aware coloring
- pane-level fills

Range is resolved through pane visual policy, not through computation.

---

## Study System

`ChartStudyRegistry` is chart-session-local.

It tracks:

- study instances
- study order
- chart-local render keys
- chart-local style state
- runtime render metadata

Study families:

- indicators
- oscillators
- constructs

Tracked study properties include:

- `instance_id`
- `dataset_id`
- `pane_target`
- `display_name`
- `computation`
- `style`
- `user_metadata`
- `runtime`

Important: UI actions (style/edit/remove) should target the stable chart-local `instance_id`. `render_keys` are renderer-facing identifiers and may be resynced after style resolution; they must not be used as durable UI identity.

`StudyUserMetadata` stores user-facing semantic context on `ChartStudyInstance`:

- `important`
- `description`
- `dataset_role`

This metadata persists through study serialization, Study Environments, and Workspace Snapshots. Per-study metadata is selected when saving or updating a Study Environment through the Save Study Environment dialog, and saved metadata can later be edited in the Study Environment Manager. The save dialog applies metadata to the serialized Study Environment payload without mutating the live chart registry. Metadata edits do not affect computation, rendering, style, runtime state, artifact identity, recipe identity, or geography truth; `dataset_role` is a hint only.

### Study lifecycle rules

- studies are chart-local
- studies do not own pane layout
- style changes do not trigger recomputation
- removal does not mutate other studies
- one controller projection may feed one or more chart-local study instances
- runtime render keys are chart-local renderer-facing identifiers, not controller computation identity

### Immutability model

Study objects are stored as frozen dataclasses and updated via replacement rather than mutation.

This preserves clear separation between:

- computation config
- style state
- runtime state

---

## Study Styling Model

Study styling is:

- chart-local
- visual-only
- owned by `HistoricalChartPanel`

User-visible style layers include:

- per-signal styling
- per-fill styling
- style modules

The legacy global compatibility layer may still exist internally for transition safety, but it is not the source of truth for defaults.

### Critical rule

Style changes must never trigger recomputation.

Style reapply must only rebuild render payloads with updated visual state.

The Style editor exposes Apply / OK / Cancel. Style editor Apply commits the current style to the live chart while keeping the dialog open; OK applies and closes; Cancel closes without applying further unapplied edits and does not roll back changes already explicitly committed through Apply. White / `#FFFFFF` is available in the style palettes.

---

## Default Style Source of Truth

Static study defaults are defined in:

`study_style_defaults.py`

This includes defaults such as:

- signal colors
- line width
- line style
- visibility
- fill color
- fill opacity

### Rules

- `study_style_defaults.py` is the single source of truth for static defaults
- panels must not hardcode semantic defaults
- renderers must not define semantic defaults
- the model must not define semantic defaults

### Enforcement

Defaults are enforced as follows:

1. defaults are resolved at apply-time
2. defaults are persisted into `ChartStudyInstance.style`
3. style modules and fill overrides layer on top of persisted chart-local study state
4. render surfaces consume only the final chart-local render state

`SeriesStyle` remains a neutral transport container, not a styling authority.

---

## Style Resolution Pipeline

Style resolution order is strict:

1. `study_style_defaults.py`
2. persisted `ChartStudyInstance.style`
3. per-fill overrides
4. style modules
5. renderer execution

No other layer may introduce semantic defaults.

Renderers are execution surfaces only.

---

## Style Modules

Style modules are chart-local, declarative runtime style state.

Examples include:

- conditional line color
- conditional fill color
- fill between signals
- directional width changes

They are:

- visual-only
- study-owned
- renderer-consumed
- computation-independent

Current HCK support uses chart-local style modules for **historical segmented conditional rendering**.

That means:

- the panel/resolver layer derives explicit bullish/bearish renderer-facing payloads from the logical `fast_vwap` / `slow_vwap` study outputs
- the renderer executes that explicit payload only
- latest-state whole-study tinting is not the intended HCK behavior
- non-renderable utility outputs such as `vwap_color` remain out of the chart renderer

---

## Spec and Naming Consumption in the GUI

The GUI consumes:

- `ft_specs.py` for metadata and semantic renderability information
- `ft_naming.py` for canonical identity

The GUI must not reconstruct canonical identity locally.

### Apply contract

Only outputs declared renderable become chart series.

Non-visual outputs may still be valid apply results, but they must not be injected into the render layer.

---

## Financial Tool Workflow

The financial tool workflow is handled by `FinancialToolsManagerWindow`.

The GUI workflow remains:

`selection → configuration → preview/apply/save`

When opened from a historical chart panel, `FinancialToolsManagerWindow` receives the configured historical root from the chart session. The constructor fallback may still exist for unsupported direct construction, but supported chart and Data Manager flows pass historical roots explicitly.

The GUI owns:

- chart-session apply integration
- chart-session style integration
- study edit/remove actions

The GUI does not own:

- computation
- persistence semantics
- runtime lifecycle

### Apply vs Save

Apply:

- chart-session operation
- compute may run on the full canonical dataset
- render payload sent to the chart is resident-local only
- no persistence occurs
- confirmed through a chart-panel-owned preflight/progress dialog before execution

Save:

- full-dataset operation
- compute runs on the full canonical dataset
- persisted output is not trimmed to the current resident slice
- saved CSV-backed artifacts are accompanied by `.meta.json` sidecars owned by the Core/data persistence layer

This distinction must stay explicit. GUI code may display and request saved artifacts, but it must not define the sidecar contract or reconstruct artifact identity locally.

Financial Tools Apply opens a preflight/progress dialog from the historical chart panel. The dialog shows the selected tool title, chart/dataset context, `Input bars to process: N`, progress state, and status/error text. Cancel is available before execution starts. Once synchronous Apply begins, progress is indeterminate, Cancel is disabled, and OK remains disabled until success or failure. Success continues through the existing controller `apply_succeeded` signal, panel success handler, workspace series application, and `ChartStudyRegistry.add(...)` path. Failure is shown in the dialog and allows OK/Close without changing the chart registration path.

Saved source selection in `FinancialToolsManagerWindow` consumes saved artifact sidecar column metadata when available. Valid `.meta.json` `selectable` / `analysis_usable` metadata is source-selection truth; CSV-header fallback exists only for legacy, missing, or malformed sidecars.

Historical save paths share the data-layer `result_to_save_dataframe(...)` helper with Data Manager/recipe calculation so chart save and save-only artifact calculation preserve boolean/state outputs, numeric values, NaN gaps, timestamp behavior, and output ordering consistently.

UTC / Universal Trend Classifier dependency preparation is shared through the data-layer `utc_dependency_sources.py` execution helper for chart apply/save and `ArtifactCalculationService`. The recovery planner consumes the shared UTC dependency-intent resolver and remains read-only while checking missing or duplicate dependency join keys.

---

## Historical vs Realtime Distinction

Historical and realtime charting share the same engine concepts, but not the same session rules.

### Historical sessions

Historical sessions use:

- controller-owned resident slicing
- full-dataset compute with resident-local render projection
- fixed historical chart-space padding
- stale-slice protection in the controller
- panel/workspace reapply of projected resident studies

### Realtime/snapshot flows

Realtime and snapshot flows use:

- current chart-process base OHLC layer
- zero historical domain padding by default
- no controller-owned historical refill path
- no GUI-side maxlen truncation as a hidden retention policy

The viewport remains a camera in both modes. It never becomes a data-retention owner.

---

## Diagnostics and Runtime Observability

The GUI may consume audit and runtime snapshots for:

- progress feedback
- error reporting
- diagnostics presentation
- recent-history inspection

Audit remains append-only and decoupled from GUI mutation logic.

Runtime truth remains in Core and `StateStore`.

---

## Key Architectural Rules

The current GUI architecture enforces:

- behavior-driven rendering
- controller-owned compute/render boundary
- controller-owned resident-slice truth
- panel-owned chart-local study lifecycle and style
- workspace-owned pane layout and pane contracts
- viewport as shared horizontal camera only
- fixed historical chart-space domain policy
- visual-only style mutation
- immutable study lifecycle state
- resident-local renderer inputs
- renderer as an execution-only layer
- public render-cache invalidation contracts instead of private panel-to-renderer cache mutation
- batched resident-study reapply for historical refresh

### Non-negotiable rules

- studies do not control layout
- workspace owns panes
- viewport does not mutate dataset truth
- panning and zooming do not redefine chart space
- style does not trigger compute
- visual policy is chart-local / pane-local
- renderers do not define defaults
- renderers do not reinterpret indexing
- renderers do not invent missing vertical truth
- defaults must persist into study state
- compute truth and render truth must stay separated by the controller boundary
- stale slices must not overwrite current resident truth
- no layer should silently take over another layer’s job

---

## Validation Basis

This README is aligned with the current validated GUI chart-stack direction across the relevant chart-session layers and companion architecture documents, especially:

- `historical_chart_controller.py`
- `historical_chart_panel.py`
- `workspace.py`
- `model.py`
- `panes.py`
- `DESIGN_historical_chart_v2.md`
- `study_readme.md`
- `core_readme.md`
- `DESIGN_financial_tools.md`
- `construct_readme.md`

Validation in this environment was static/structural rather than live Qt runtime because `PySide6` was unavailable in the container.

This version also includes a focused structural validation pass for viewport-refresh ownership, single-shot pane/surface contract application, and Historical Notebook ownership boundaries.

This README therefore documents the current ownership contract and validated code direction, not a final live-runtime sign-off.

---

## Summary

The GUI currently provides:

- 8-slot adaptive historical workspace with Scroll 4 / Fit 8 modes, dock-back slot preservation, and chart Position controls
- Historical Notebook support for workspace-linked notes, Potential Trades, POIs, row-level delete, explicit Go navigation, assigned snapshot notebooks with immediate notebook indicator refresh, dirty close/load replacement prompts, rich-text free-text formatting, and runtime POI/PT chart annotations
- Notebook Manager ownership for notebook assignment/unassignment, assignment summaries, and confirmed notebook deletion
- Pan Anchor horizontal synchronization across active historical charts
- confirmed delete actions for saved Study Environments and Workspace Snapshots
- detachable chart sessions
- shared chart engine for embedded and floating shells
- pane-managed layout
- workspace-owned price-pane autoscale / manual-y behavior
- fixed historical chart-space domain policy
- controller-owned resident slicing
- managed overlay grouping
- multi-series study support, including BB, HCK, and the marker-style `peaks_troughs` price-pane event study
- chart-local duplicate-study identity over shared controller projection truth
- chart-local layered styling
- historical segmented conditional rendering resolved upstream of the renderer
- chart-local oscillator visual policy
- bounded oscillator rendering
- threshold-aware coloring
- pane-local vertical interaction
- centralized Runtime Inspector diagnostics
- OHLCV Maintenance for explicit validation, repair, source-invalid reporting, provenance-recorded source correction, and modified status display
- Research Suite chart creation limited to accepted `ok` / `modified` OHLCV datasets through CoreBridge/HistoricalDatasetService loadability gates
- managed Data Manager window for accepted-OHLCV dataset/artifact preparation, metadata-aware Analysis Database seed creation, selected Analysis Database extension from recipe collections, selected artifact/database update workflows, separate build/rebuild, explicit component editing, recipe/collection recovery, compact maximized M6F layout, 60% usable-width dialog polish, rename/delete, and read-only preview workflows
- Workspace Snapshot load preflight with indeterminate synchronous loading state
- Download Manager progress throttling/coalescing in the GUI layer
- polling-based runtime visibility
- explicit `CoreBridge`-owned realtime control boundary

Most importantly, the GUI now respects the intended historical chart pipeline contract:

- OHLC remains canonical chart truth
- the controller owns full-dataset and resident-slice truth
- the panel owns chart-local study lifecycle, style, and duplicate-instance identity
- the workspace owns chart-space policy, panes, and pane contracts
- the viewport is only the camera
- panes are only the handoff boundary
- renderers execute resident-local, chart-local truth without semantic reinterpretation
---

## Refactored GUI Source Layout — 2026-04-20
This section records the current GUI refactor baseline. It does not change the ownership model documented above; it makes that model physically auditable.

### Stable public façades

```python
from leonardo.gui.historical_chart_controller import HistoricalChartController
from leonardo.gui.windows.historical_chart_panel import HistoricalChartPanel
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.chart.panes import PricePane, VolumePane, OscillatorPane
from leonardo.gui.chart.chart_render import ChartRenderSurface
from leonardo.gui.chart.series_render import VolumeRenderSurface, OscillatorRenderSurface
```

### Controller internals

```text
gui/historical_chart_controller.py          # public QObject façade
gui/historical_chart/
    session.py
    data_access.py
    construct_sources.py
    refill_policy.py
    projection.py
    tool_execution.py
```

### Workspace internals

```text
gui/chart/workspace.py                      # public façade
gui/chart/_workspace/
    __init__.py
    workspace_state.py
    workspace_batches.py
    workspace_autoscale.py
    workspace_overlays.py
    workspace_oscillators.py
    workspace_apply.py
    workspace_contracts.py
```

`workspace.py` remains the public import. The private `_workspace` package contains implementation details only.

### Pane package

```text
gui/chart/panes/
    __init__.py
    contracts.py
    header_widgets.py
    overlay_rows.py
    price_pane.py
    volume_pane.py
    oscillator_pane.py
```

Panes remain narrow handoff boundaries.

### Renderer package

```text
gui/chart/rendering/
    __init__.py
    right_axis_tags.py
    time_axis.py
    y_axis_interaction.py
    candle_painter.py
    overlay_painter.py
    fill_painter.py
    marker_painter.py
    surface_painter.py
    volume_surface.py
    oscillator_policy_painter.py
    oscillator_surface_painter.py
```

Renderers remain execution-only. They draw resident-local payloads and consume explicit pane-owned y-range/policy state.

### Historical chart panel internals

```text
gui/windows/historical_chart_panel.py        # public façade
gui/windows/_historical_chart_panel/
    __init__.py
    historical_chart_panel_study_apply.py
    historical_chart_panel_style.py
    historical_chart_panel_oscillator_policy.py
    historical_chart_panel_projection_bridge.py
    historical_chart_panel_messages.py
    study_style_dialog.py
```

The private helper package avoids cluttering `gui/windows` while preserving `historical_chart_panel.py` as the public file.

### Autoscale baseline

The user-facing Autoscale button maps to workspace-owned price-pane vertical fitting:

```python
ChartWorkspaceWidget.price_autoscale_enabled
ChartWorkspaceWidget.set_price_autoscale_enabled(...)
```

Legacy `set_anchor_zoom_enabled(...)` remains a compatibility alias only. The viewport is still horizontal camera state, not Autoscale ownership.

### Packaging hygiene

Production GUI archives should not include `__pycache__/`, `.pyc`, `.pytest_cache/`, or `.git/` unless the archive is intentionally a full development snapshot.

Recommended tooling (in the GUI package):

- `gui/tools/release_checks.py` — static contract + hygiene checks
- `gui/tools/package_clean_zip.py` — produces a clean zip after checks pass

---

## Change log

- **v3.41 (2026-05-30)** - Analysis Suite AS10-AUDIT sync: documents that POI family comparison and white-box rule-discovery architecture is design-only, AS10 GUI controls remain future work, and future GUI code must not compute white-box rule metrics, persist definitions/reports, or own backend rule policy.

- **v3.40 (2026-05-30)** - Analysis Suite AS-GUI-3 sync: documents the accepted Genome Path Preview UI in `AnalysisSuiteWindow`, including AS9 encoding definition controls, component rows, validation, row-anchored and POI-family-anchored path previews, stale genome state clearing, no persistence, no direct dataframe or manifest policy reads, no Dynamic Binner fitting, no full Variation Analyzer, and no AS10 white-box/rule-discovery behavior.

- **v3.39 (2026-05-30)** - Analysis Suite AS-GUI-2 sync: documents the accepted POI / Family Preview UI in `AnalysisSuiteWindow`, including AS8 POI definition controls, family condition rows, occurrence and membership preview rendering, stale POI/family state clearing, no persistence, no direct dataframe or manifest policy reads, no AS9 genome path controls, and no category-builder or white-box behavior.
- **v3.38 (2026-05-30)** - Analysis Suite AS-GUI-1 sync: documents the accepted Target / Feature / Diagnostic Preview UI in `AnalysisSuiteWindow`, including Data Preview, Target Preview, Feature Set, and Diagnostic Report tabs; AS5/AS6/AS7 service ownership; stale-state clearing; no persistence; no direct dataframe or manifest policy reads; no AS8/AS9 controls; and layout polish as future work.
- **v3.37 (2026-05-30)** - Analysis Suite GUI audit sync: documents AS-GUI-AUDIT, recommends AS-GUI-1 as Target / Feature / Diagnostic Preview UI, stages later AS-GUI-2 POI/family and AS-GUI-3 genome path previews, and preserves the boundary that this is design only with no GUI implementation, persistence, stores, model/training/signal behavior, database mutation, or OHLCV repair.
- **v3.36 (2026-05-30)** - Analysis Suite genome path builder AS9 sync: documented `AnalysisSuiteGenomePathBuilder` as backend-only, read-only genome/path preview planning, clarified row-anchored and AS8-family-anchored preview scope, and preserved the GUI boundary that `AnalysisSuiteWindow` still exposes only catalog and bounded dataframe preview with no genome/path controls or genome persistence.
- **v3.35 (2026-05-29)** - Analysis Suite POI/family planner AS8 sync: documented `AnalysisSuitePoiFamilyPlanner` as backend-only, read-only POI occurrence and family membership planning, clarified AS1/AS7 gating and manifest-metadata validation, and preserved the GUI boundary that `AnalysisSuiteWindow` still exposes only catalog and bounded dataframe preview with no POI/family/category controls or POI/family persistence.
- **v3.34 (2026-05-28)** - Analysis Suite diagnostic report AS7 sync: documented `AnalysisSuiteDiagnosticReportService` as backend-only, read-only composition of AS1 readiness, AS5 target preview, and AS6 feature-set preview reports; clarified that `AnalysisSuiteWindow` still exposes only the read-only catalog and bounded dataframe preview, with no target, feature-set, diagnostic, persistence, project/run/report, model, signal, artifact, recipe, database materialization, or OHLCV repair controls.
- **v3.29 (2026-05-28)** - Data Manager selected update sync: documented 60% usable-screen-width Data Manager dialogs, `DataManagerSelectedUpdateService`, selected artifact/database `Check Update` and `Update Selected...` controls, OLD/DRAFT status semantics, synchronous preflight/report dialogs, and unchanged GUI/data ownership boundaries.
- **v3.28 (2026-05-28)** - Post-smoke correction sync: documented DM3 extend-only recipe collection database workflow, DM2 Data Manager dialog/highlight polish, RS8 Style editor Apply behavior, RS9 notebook indicator refresh, RS10 Workspace Snapshot load preflight/loading, and DL1 Download Manager GUI-layer progress throttling.
- **v3.27 (2026-05-26)** - Research Suite notebook UX RS5 sync: documented notebook dirty-state protection, Save / Don't Save / Cancel close/replace flow, rich-text formatting palettes for notebook free-text fields, plain-text compatibility, and optional parallel HTML fields.
- **v3.26 (2026-05-26)** - Research Suite RS1-RS4 sync: documented Research Suite terminology, artifact-save recipe persistence and sidecar recipe metadata, notebook Save as new / Update existing, and Study Environment / Workspace Snapshot managers with read-only embedded snapshot study metadata.
- **v3.25 (2026-05-26)** - Historical Study metadata action and save update-mode sync: documented the earlier chart-local metadata action baseline plus Save as new / Update existing modes for Study Environments and Workspace Snapshots. RS7 supersedes the chart-row action placement with Save/Update Study Environment metadata controls.
- **v3.24 (2026-05-26)** - Study metadata and Data Manager recipe-to-database workflow sync: documented chart-local `StudyUserMetadata`, `Create Recipes from Study Environment...`, C1 geography reporting, C2 recipe-collection artifact resolution, and C3 data-layer draft/extend service. DM3 later superseded the user-facing collection database workflow with selected-database-only extension while preserving no-calculation and no-materialization boundaries.
- **v3.23 (2026-05-25)** — OHLCV acceptance workflow documentation sync: Historical Download Manager preliminary validation remains non-certifying, OHLCV Maintenance is documented as the explicit validation/repair/source-correction window, Research Suite chart creation is gated to `ok` / `modified` OHLCV, and Data Manager selector/preview behavior now consumes CoreBridge/data-layer loadable catalogs.

- **v3.22 (2026-05-22)** — Historical apply/save/recovery hardening: Financial Tool Manager saved-source selection now consumes sidecar column metadata, historical runtime projection prefers explicit timeline/index alignment before legacy positional fallback, chart save and save-only artifact calculation share result-to-save-dataframe conversion, and UTC dependency preparation/recovery intent resolution are centralized while preserving chart/session ownership boundaries.

- **v3.21 (2026-05-22)** — Historical download/Core capability sync: Historical Download Manager capability display remains GUI intent/display only, while CoreBridge resolves exchange capabilities through the registered Core `ExchangeRegistry`; downloader adapter acquisition is registry-backed, normalized audit snapshots remain GUI-displayable, and GUI ownership boundaries are preserved.

- **v3.20 (2026-05-22)** — Historical Notebook and workspace final polish: Notebook Manager owns assignment and deletion, Notes rows no longer navigate, Trades became Potential Trades, Potential Trades support explicit Long/Short direction and runtime green/red arrow annotations, POI/PT marker offsets persist in notebook `annotation_settings`, saved Study Environment and Workspace Snapshot load dialogs gained confirmed Delete actions, Research Suite opens maximized, and Pan Anchor provides optional horizontal timestamp-based pan synchronization across active charts. Later RS5 updates added dirty close/load replacement prompts.

- **v3.19 (2026-05-21)** — Historical Notebook workflow: added `Notes` menu notebook actions, `HistoricalNotebookStore` persistence, Workspace Snapshot `notebook_ref`, dataset-keyed notebook chart tabs, structured Notes/Trades/POI rows, row-level `Go` buttons, runtime POI chart annotations, and the menu-bar `Notebook` quick action. Study Environments remain notebook-free and POI markers remain runtime annotations rather than hidden studies.

- **v3.18 (2026-05-20)** — Historical workspace compact-layout polish: chart-area margins, embedded grid gaps, splitter handle width, and renderer plot padding were reduced; pane separation is handled by subtle borders/separators; `Scroll 4` / `Fit 8` moved into the `Window` menu; a top-right menu-bar label displays the current visualization mode. Historical domain padding and controller/refill behavior are unchanged.

- **v3.17 (2026-05-20)** — Root and boundary documentation sync: GUI/chart/download paths pass configured historical roots explicitly, `WindowManager` registration is documented as GUI-owned lookup, `CoreBridge` ignores stale realtime future completions, and Data Manager main widgets use the shared right-side button rack layout.

- **v3.16 (2026-05-19)** — Historical Workspace layout update: embedded Research Suite charts now support 8 stable logical slots, Scroll 4 / Fit 8 visualization modes, dock-back slot preservation, chart Position controls, and adaptive visual layouts for 1–8 embedded charts.

- **v3.15 (2026-05-18)** — Historical chart/study hardening: Core-backed dataset selection, dataset-open/slice stale-result guards, temporary analysis-source preservation for non-renderable outputs, empty-render rejection unless explicitly allowed, public render-cache invalidation contracts, Sequence-safe series values, and CoreBridge dataset-cache refresh intent.

- **v3.14 (2026-05-18)** — Historical Download Manager documentation sync: GUI displays adapter/capability-provided markets and timeframes, requests Core-owned preflight and confirmed downloads, observes audit/task state, and routes Stop/Cancel through CoreBridge without owning exchange-specific truth or async execution.

- **v3.13 (2026-05-16)** — Data Manager M6F visual baseline: maximized opening, compact top/middle/lower layout, enlarged local font, bold widget titles, compact DataFrame Preview header, saved-artifact actions above the list, and equal Database Builder list/details display space. Data ownership and Analysis Database semantics are unchanged.

- **v3.12 (2026-05-13)** — Data Manager Analysis Database workflow hardening: database names default to `SYMBOL_timeframe_`, whitespace names and duplicate visible names are rejected through store-owned semantics, checkbox-based database selection was introduced, and durable database operations remain `AnalysisDatabaseStore`-owned.

- **v3.11 (2026-05-12)** — Data Manager documentation baseline: `DataManagerWindow` is a managed top-level artifact workflow window, separate from chart sessions; saved artifact metadata sidecars and restore-only data checks remain Core/data-owned semantics.

- **v3.10 (2026-04-24)** — Style reapply hardening: style edits invalidate static-scene caches so color changes apply immediately; managed overlay actions route by chart-local `instance_id` rather than render keys to avoid render-key drift.

- **v3.9 (2026-04-23)** — Contract-first hardening: workspace remains the sole viewport-refresh owner, volume refresh is fully normalized through pane contracts, render surfaces consume one-shot `apply_contract(...)` handoffs, and packaging guardrails were added for clean release zips.

- **v3.8 (2026-04-21)** — Render-efficiency hardening: workspace-owned viewport refresh reconciliation, single-shot pane→surface contract application for price/oscillator/volume surfaces, reduced overlay-card layout churn, time-axis tick caching, and path-batched overlay drawing.
