🧠 Leonardo — Roadmap

Version: v0.35
Status: Living document (expected to change)
Updated: 2026-05-28

Purpose

Leonardo is a Python-first application whose main goal is to act as an advisor for financial trades.

It is designed to be modular, auditable, and resilient, with a strong emphasis on:

data correctness
risk controls
explainable (“white-box”) analytics

------------------------------------------------------------
1) CORE
------------------------------------------------------------

Purpose: Application foundation: lifecycle, runtime state, reliability, and auditability.

Responsibilities

Runtime lifecycle

Explicit application lifecycle management:

starting
running
stopping
stopped
failed

Deterministic startup/shutdown sequencing
Service initialization and teardown coordination

------------------------------------------------------------

Runtime state (authoritative layer)

Explicit runtime state surface maintained via StateStore

Tracks:

application state
lifecycle-managed services and their lifecycle
active background tasks
GUI-exposed runtime elements (windows, realtime flags)

Phase 3 additions:

connection runtime state (external operational connections)
session runtime state (minimal runtime session identity)

Connection runtime state tracks:

connection identity (feed-level ownership)
connection kind (e.g. market_data)
lifecycle state:

registered
starting
running
stopping
stopped
failed

last error (if any)

Enforces:

single-writer mutation model
controlled state transitions
idempotent updates

Key principle:

Runtime state represents current truth

------------------------------------------------------------

Connection lifecycle model (Phase 3)

Connection lifecycle is owned by orchestration code (e.g. feed tasks).

Important constraints:

connection runtime state is emitted at the feed/orchestration level
exchange adapters remain transport-only
GUI does not own connection lifecycle

Adapters must NOT:

emit runtime state
track lifecycle state
depend on StateStore

This ensures:

clear separation between transport and runtime truth
consistent visibility of external dependencies
deterministic and debuggable connection behavior

------------------------------------------------------------

Task supervision

Centralized async task management via TaskManager

Task lifecycle tracking:

started
completed
failed
cancelled

Integration with runtime state and audit layer
Coordinated shutdown with cancellation and timeout control

Phase 2 rule:

Runtime task state contains only active tasks

Completed, failed, and cancelled tasks are:

removed from runtime state
preserved exclusively in audit history

------------------------------------------------------------

Service management

Registration of long-lived runtime services

Explicit service lifecycle tracking (lifecycle-managed services only):

registered
starting
running
stopping
stopped
failed

Deterministic startup order and reverse shutdown order

------------------------------------------------------------

Service registration model (Phase 2)

Services are registered explicitly via AppContext

Two categories exist:

Lifecycle-managed services
participate in startup/shutdown
tracked in runtime state
included in lifecycle transitions

Capability providers
long-lived objects available via service lookup
do NOT participate in lifecycle tracking
not included in runtime service lifecycle state

This separation ensures runtime lifecycle state reflects only services that actually participate in lifecycle transitions.

------------------------------------------------------------

Audit and observability (foundation layer)

Structured audit event emission for all meaningful runtime transitions

Provides:

in-memory audit inspection
durable JSONL audit logging
fail-safe audit emission

Key principle:

Audit represents historical truth

Phase 2 refinement:

Runtime-origin audit events are constructed through a centralized emission path in StateStore

This ensures:

consistent event structure
stable entity identification
reliable downstream diagnostics

------------------------------------------------------------

Registry (transitional compatibility layer)

Maintains legacy get/set access pattern

Provides:

compatibility access for runtime payloads only

Phase 2 constraints:

Registry writes are restricted to runtime payloads
Service objects must NOT be stored in the registry
Service objects must be registered explicitly via AppContext

Important:

Runtime truth is owned by StateStore
Service access is explicit
Registry is transitional and will be phased out

------------------------------------------------------------

Configuration and bootstrap

Configuration loading and environment profiles
Folder tree checks + bootstrap validation
Core initialization sequence

------------------------------------------------------------

Error handling

Centralized error routing
Structured error reporting
Integration with audit layer
Safe shutdown on critical failures

------------------------------------------------------------
2) ENGINE / ORCHESTRATION
------------------------------------------------------------

Purpose: The “nervous system” coordinating GUI, data, connections, and analytics while enforcing boundaries.

(Currently NOT implemented — future phase)

Responsibilities (planned):

Event bus / pub-sub
Task scheduling
Pipeline execution
Dependency boundary enforcement
Concurrency model
Coordination between GUI bridge and core runtime

------------------------------------------------------------
3) GUI
------------------------------------------------------------

Purpose: User interaction and visualization. No trading logic inside.

Current state:

GUI acts as a thin interaction layer connected to Core via CoreBridge.

Important notes:

Current MainWindow is a temporary integration surface used for:

runtime validation
chart verification
temporary realtime control testing

Phase 4 refinement:

Realtime feed start/stop now flows through an explicit CoreBridge command boundary.

Current behavior:

MainWindow requests realtime actions through CoreBridge
CoreBridge owns the temporary realtime feed future
CoreBridge ignores completion callbacks from stale realtime futures that are no longer active
GUI no longer launches feed tasks directly
GUI reacts to bridge signals and runtime state instead of owning feed lifecycle

Future direction:

Dedicated connection management UI
Improved status/error presentation in the GUI layer
Further separation of temporary test-harness behavior from final connection UX

Responsibilities (target):

Charting system for historical and realtime data
Multi-pane chart layouts
Shared viewport interaction model
Workspaces and layout persistence
Dashboards and system visibility

------------------------------------------------------------
4) CONNECTION
------------------------------------------------------------

Purpose: External IO: streams + APIs + credentials + resilience.

Current state:

Basic exchange adapter and feed execution implemented.
Connection lifecycle now visible via runtime state (Phase 3).
GUI-driven direct feed orchestration removed in favor of explicit CoreBridge control flow (Phase 4).

Important constraints:

Adapters are transport-only
Connection lifecycle is owned by feed/orchestration layer
GUI must not own feed futures or adapter lifecycle
No reconnection framework implemented yet

Planned responsibilities:

Websocket management
API clients
Retry and rate limiting
Connection health monitoring

------------------------------------------------------------
5) DATA MANAGEMENT
------------------------------------------------------------

Current direction:

Data management now includes artifact preparation for analysis workflows in addition to historical OHLCV ingestion.

Implemented baseline:

- `DataManagerWindow` introduced as a top-level managed GUI window under the Analysis workflow.
- Analysis Database contract, naming policy, draft manifest workflow, materialization, explicit component editing, and read-only dataframe preview were introduced.
- Analysis Databases are stored under `analysis_databases/{database_id}/` with `manifest.json` and optional/materialized `dataframe.csv`.
- AS1 added the read-only `AnalysisSuiteDatasetReadinessService` for Analysis Suite dataset consumption. It reports `ready`, `draft`, `missing_dataframe`, `stale_source`, `incomplete_topology`, `corrupt_manifest`, `corrupt_dataframe`, `blocked`, and `error` readiness states without adding project/run/report stores, model logic, artifact calculation, database materialization, or OHLCV repair.
- AS2 added `AnalysisSuiteWindow`, the first read-only Analysis Suite GUI surface, opened from `Analysis -> Analysis Suite`. `Analysis -> Data Manager` remains the separate preparation workflow. The window displays AS1 readiness reports and can route users back to Data Manager without mutating databases.
- AS3/AS4 added bounded dataframe preview for `AnalysisSuiteWindow` through `AnalysisSuiteDataframePreviewService`. The catalog supports Head/Tail previews with AS1 `can_preview` gating, service-enforced default `100` / max `500` row limits, JSON-safe rows, and raw `ts_ms` plus `ts_utc` / `ts_rome` display fields when available. The GUI does not load `dataframe.csv` directly and does not create projects/runs/reports, train models, generate signals, calculate artifacts, repair OHLCV, or build/rebuild/materialize databases.
- AS5 added the backend-only read-only `AnalysisSuiteTargetPlanner` with `AnalysisSuiteTargetDefinition` and `AnalysisSuiteTargetPreviewReport`. It previews future return regression and future direction classification labels in memory, uses positive `horizon_bars` alignment back to timestamp `t`, marks the last `N` rows unavailable, gates through AS1 `can_preview`, and reports leakage metadata marking label outputs as `target_only`, `future_derived`, and not feature-eligible. It does not add GUI wiring, target/label persistence, projects/runs/reports, model logic, signals, artifact calculation, recipe execution, OHLCV repair, or Analysis Database mutation.
- `Database seed creator` creates named database seeds with dataset-prefix defaults such as `BTCUSDT_30m_`, no-whitespace validation, and same-market duplicate-name rejection.
- Checked saved artifact columns feed the `Database seed creator` only; they do not feed Database Builder.
- Saved artifact column discovery is shared through a GUI-owned loader so the main selector, build dialog, and component editor use the same artifact listing behavior.
- `Database Builder` supports exactly-one checked database selection for separate build, rebuild, component edit, rename, delete, and preview actions.
- `Build Selected Database` opens a dedicated build dialog that auto-loads saved artifacts, highlights already-present components, and materializes the selected database from its existing saved manifest recipe.
- `Rebuild Selected Database` rewrites `dataframe.csv` for a materialized database from the same saved manifest recipe.
- Build/rebuild preserves `database_id`, folder, display name, feature sources, feature columns, and recipe hash; it does not add, remove, or replace artifact components.
- `Edit Selected Database Components...` is the explicit workflow for add/remove/replace component changes. It auto-loads saved artifacts, highlights already-present components, updates the saved recipe through the data-layer component editor, resets materialization to draft, and requires a later build.
- Already-present Saved Artifact Columns in the component editor use light green `#C8F7C5` background, black foreground, and bold font; non-present rows keep normal styling.
- Analysis Database rename preserves immutable `database_id`; delete removes the folder-backed artifact.
- Duplicate visible-name validation applies to draft creation and rename, not to build/rebuild of an existing database by `database_id`.
- Data Manager opens maximized and uses the accepted M6F compact visual layout: Dataset and Calculate and Save Tool Outputs on the top row, DataFrame Preview and Saved Indicators / Oscillators / Constructs on the middle row, Data Checks / Metadata Tools plus Database seed creator on the lower-left area, and Database Builder on the lower-right area.
- Main Data Manager widgets use the shared right-side button rack for actions.
- Data Manager button racks have a 260px minimum width, and the artifact calculator popup opens at 60% of usable screen width and height while preserving its 900x620 minimum size.
- DataFrame Preview keeps source, row-limit, and visible timestamp information in the content header while its action remains in the shared button rack.
- Saved artifact actions and Database Builder actions use the shared button rack so lists and details retain content width.
- Data Manager-local text is enlarged and widget titles are bold while normal labels/buttons remain normal weight.
- Saved Artifact Recipes and Saved Recipe Collections dialogs now use larger/readable list areas for long names.
- Saved Artifact Recipes, Saved Artifact Recipe Collections, Edit Analysis Database Components, and Extend Analysis Database from Collection dialogs now open at 60% of usable screen width while preserving minimum-size policy.
- CSV-backed historical artifacts use adjacent `.meta.json` sidecars for identity, metadata, lineage, fingerprint, and quality metadata.
- OHLCV writes produce `candles.csv` plus `candles.meta.json`.
- Derived indicator, oscillator, and construct saves produce `<instance_key>.csv` plus `<instance_key>.meta.json`.
- Metadata backfill exists as a restore-only maintenance layer for missing or unreadable sidecars. It must not rewrite CSV values and must not silently refresh valid metadata.
- Save-only financial-tool artifact calculation is available through Data Manager and preserves the Apply vs Save boundary.
- Artifact recipes are persisted as reusable full-dataset calculation instructions under `artifact_recipes/`.
- Artifact recipe collections are persisted under `artifact_recipe_collections/` as ordered embedded recipe snapshots with optional dependency metadata and optional `source_database_id` linkage.
- M4 recovery workflow is implemented:
  - M4A `ArtifactRecoveryPlanner` performs read-only artifact/source status classification.
  - M4B `ArtifactRecoveryRegenerator` regenerates planner-actionable artifacts by delegating to `ArtifactRecipeExecutor`.
  - M4C `ArtifactRecoveryDatabaseRebuilder` gates and delegates linked Analysis Database materialization to `AnalysisDatabaseStore`.
  - M4D exposes recovery status, actionable artifact recovery, and linked database rebuild actions in the Data Manager recipe-collection UI.
- M5 hardening is accepted:
  - M5A added regression coverage for rebuild identity, manifest-recipe preservation, checkbox selection, timestamp preview, and Data Manager boundary behavior.
  - M5B added GUI release guardrails that fail if Database Builder consumes artifact selections or replaces database components during rebuild.
  - M5C synchronized Data Manager documentation.
  - M5D validated release readiness.
- M6 Data Manager component/edit/build UX is accepted:
  - M6B added the data-layer `AnalysisDatabaseComponentEditor`.
  - M6C extracted the shared GUI feature-builder helper.
  - M6D added the explicit component editor GUI.
  - M6E split build/rebuild, added the dedicated build dialog, auto-loaded saved artifacts in build/edit dialogs, highlighted existing components, enlarged recipe/collection dialogs, and validated the final smoke test.
  - M6F finalized Data Manager visual polish: maximized opening, compact top/middle/lower screen layout, shared right-side button rack placement, improved DataFrame Preview content header, equal Database Builder list/details display space, enlarged local font, and bold widget titles without changing data semantics.
- M7 Historical Download Manager hardening is accepted:
  - M7A kept exchange-specific markets, timeframes, aliases, interval mappings, and limits in the adapter/capability layer instead of the GUI.
  - M7B wired Historical Download Manager market/timeframe display through CoreBridge capability callbacks.
  - M7C added metadata-aware preflight/range discovery and readable Confirm OHLCV Download plans.
  - M7D accepted multi-timeframe OHLCV selection, task monitor progress, Stop/OK flow, final recap, and batch validation summary.
  - M7E made Bybit's historical page limit adapter-owned, with GUI `Limit = 0` resolving to the adapter default and explicit values clamped to the adapter maximum.
  - M7F normalized validation so fixed canonical timeframes such as `3m`, `2h`, `6h`, and `12h` validate without moving exchange-specific support truth into the validator.
  - M7G aligned download preflight and execution with the configured historical root, `Path(ctx.config.runtime.data_dir) / "historical"`; supported GUI flows now submit plain intent and CoreBridge resolves the root before constructing downloader requests.
- M8 Historical chart/study hardening is accepted:
  - M8A hardened historical dataset opening with GUI-thread result marshalling, open-generation guards, and stale slice-result protection.
  - M8B moved historical chart dataset selection onto CoreBridge/HistoricalDatasetService catalog surfaces instead of GUI filesystem discovery.
  - M8C preserved non-renderable `analysis_usable` outputs as temporary construct sources while keeping them out of chart rendering.
  - M8D made empty render payloads fail loudly unless a tool explicitly declares `accepts_empty_render_output`.
  - M8E synchronized construct metadata so braid width/compression stay non-renderable analysis outputs and construct outputs can be used as construct sources.
  - M8F saved full-dataset artifacts now receive explicit params/bindings/source lineage where available, and active construct saved identity includes deterministic `__h<hash8>`.
  - M8G replaced panel private render-cache reach-through with public workspace/pane/surface invalidation contracts and enforced `Sequence`-safe series values handling.
  - M8H added dataset-service cache invalidation after OHLCV rewrites and completed full uploaded test validation.
  - M8I aligned historical chart saved-artifact lookup, chart save, and chart-opened Financial Tool Manager paths with the configured historical root.

- M9 Oscillator/rendering and historical workspace polish is accepted:
  - Volume is accepted as an oscillator-pane study with histogram bars and configurable `volume_mean_{period}`.
  - Oscillator threshold coloring now splits rendered line segments at actual threshold crossings instead of coloring whole segments by endpoint state.
  - Dynamic oscillator default-style resolution now handles RSI, ARSI, MFI, SMI, TDI RSI, OBV, and Volume emitted names.
  - ARSI has been upgraded to an Ultimate RSI-style two-line oscillator with configurable smoothing and an orange signal/mean line.
  - ARSI uses dedicated `80 / 50 / 20` visual guide levels while RSI/MFI keep `70 / 50 / 30`.
  - Historical workspace compact layout reduces chart-area margins, pane gaps, splitter width, and renderer plot padding without changing domain-padding/refill behavior.
  - Historical workspace visualization mode controls moved to the `Window` menu and the menu bar shows the current mode.

- M10 Notebook / Workspace Snapshot integration is accepted:
  - Research Suite exposes `Notes` menu actions for creating, opening, saving, loading, and managing notebooks.
  - `HistoricalNotebookStore` persists notebook JSON under `chart_presets/notebooks` while `HistoricalNotebookWindow` remains an in-memory editor.
  - Workspace Snapshots store only optional `notebook_ref` metadata and never embed notebook content.
  - Notebook chart tabs are keyed by dataset identity, not by chart position.
  - Notes, Potential Trades, and Points of Interest use structured rows with explicit delete/navigation behavior.
  - POI rows and eligible Potential Trades rows can produce runtime chart markers; those markers are notebook annotations, not hidden studies or financial-tool outputs.
  - The menu-bar quick actions include an `Open Notebook` / `Notebook` button before Study Environment actions when an assigned notebook is available.

- M11 Historical Notebook / preset delete / Pan Anchor polish is accepted:
  - Notebook Manager owns notebook assignment/unassignment, assignment summaries, descriptions/last-save visibility, and confirmed notebook deletion.
  - Notebook assignment truth remains only in Workspace Snapshot `notebook_ref`; notebook files do not store assigned-workspace truth.
  - Notes rows no longer navigate; Potential Trades rows have explicit `Go`, `Delete`, empty-by-default `Direction`, and Long/Short marker semantics.
  - Potential Trade Long markers render as green upward arrows below bars; Potential Trade Short markers render as red downward arrows above bars.
  - Notebook JSON persists additive `annotation_settings` for POI, PT Long, and PT Short marker offsets.
  - Later RS5 notebook UX superseded the earlier close-save path with Save / Don't Save / Cancel dirty-state confirmation.
  - Study Environment and Workspace Snapshot load dialogs expose confirmed Delete actions; Workspace Snapshot deletion does not delete referenced notebooks.
  - Research Suite opens maximized.
  - Pan Anchor is accepted as an off-by-default, horizontal-only, timestamp-center pan synchronization mode across active charts in the same Research Suite.

- M12 Historical apply/save/recovery hardening is accepted:
  - Historical Download command boundary cleanup moved downloader request/root construction behind CoreBridge while the GUI passes plain intent and observes audit/task state.
  - TaskManager terminal cleanup removes completed, failed, and cancelled tasks from its active internal task map while preserving terminal history in audit.
  - Historical runtime projection now prefers explicit `ts_ms` / `time` / non-positional index alignment before the legacy full-dataset/no-timeline positional fallback.
  - Financial Tool Manager saved-source selection consumes saved artifact sidecar `selectable` / `analysis_usable` metadata as source-selection truth, with CSV-header fallback only for legacy or malformed sidecars.
  - Chart save and save-only artifact calculation share `result_to_save_dataframe(...)` so full-dataset saved values preserve timestamps, output order, boolean/state outputs, numeric values, and gaps consistently.
  - Historical UTC Peaks & Troughs dependency preparation is centralized in `utc_dependency_sources.py` for chart apply/save and `ArtifactCalculationService`, preserving trend/range intent, overrides, configured-root lookup, and deterministic `ts_ms` / `time` alignment.
  - ArtifactRecoveryPlanner shares UTC dependency-intent resolution, remains read-only, and blocks unsafe UTC dependencies with missing or duplicate join keys.
  - Consolidated historical validation passed the focused Core/download/chart/data/recovery suite and confirmed no new layering violations in the historical scope.

- M13 OHLCV acceptance and loadability chain is accepted:
  - Historical Download Manager runs preliminary `HistoricalDatasetValidator` reporting but writes new OHLCV metadata as `validation.status = "unknown"` and `quality.validation_status = "not_validated"`.
  - OHLCV Maintenance is accepted as the explicit validation, repair, source-invalid reporting, source-correction, provenance, and `modified` status workflow.
  - Accepted/loadable OHLCV statuses are `ok` and `modified`; `unknown`, `not_validated`, `warning`, `error`, stale fingerprints, missing/unreadable metadata, metadata mismatch, and missing CSV are blocked.
  - Research Suite chart creation uses CoreBridge/HistoricalDatasetService loadable catalogs and `HistoricalDatasetService.open_dataset(...)` enforces the final load gate.
  - Data Manager Patch A added data-layer gates through `evaluate_ohlcv_dataset_loadability(...)`, `require_ohlcv_dataset_loadable(...)`, `format_ohlcv_loadability_error(...)`, `ArtifactCalculationService`, `AnalysisDatabaseStore`, and `ArtifactRecoveryPlanner`.
  - Data Manager Patch B moved selector and OHLCV preview behavior onto CoreBridge/data-layer loadable catalog surfaces, labels modified datasets, and shows OHLCV Maintenance guidance when no validated datasets are available.

- M14 Data Manager metadata/lineage hardening is accepted:
  - `build_source_ohlcv_provenance_snapshot(...)` records accepted source OHLCV identity, relative CSV/metadata paths, validation status, quality status, validation fingerprint, current CSV fingerprint, capture timestamp, and source-correction provenance when applicable.
  - Derived artifact sidecars store the source snapshot under `source_ohlcv.snapshot`.
  - Analysis Database materialization metadata stores the source snapshot under `source_ohlcv.snapshot`.
  - Analysis Database rebuild refreshes materialization source provenance instead of preserving stale source metadata.
  - Modified source snapshots preserve source-correction provenance and `needs_source_recheck`.
  - Existing legacy sidecars/manifests without source snapshots remain loadable through existing metadata extension behavior.

- M15 Recovery source-drift classification is accepted:
  - `SourceOhlcvDriftReport`, `extract_source_ohlcv_snapshot(...)`, `compare_source_ohlcv_snapshots(...)`, and `build_source_ohlcv_drift_report(...)` compare recorded `source_ohlcv.snapshot` metadata against current accepted OHLCV truth.
  - `ArtifactRecoveryPlanner` classifies source OHLCV drift inside the existing recovery status model.
  - Source-drifted artifacts are stale and planner-actionable only through the existing explicit recovery execution path.
  - Legacy artifacts missing `source_ohlcv.snapshot` remain compatible as `freshness_unknown` / lineage unknown.
  - Blocked current OHLCV blocks recovery actionability.
  - `ArtifactRecoveryRegenerator` continues delegating through `ArtifactRecipeExecutor`.
  - `AnalysisDatabaseStore.materialization_source_ohlcv_drift_report(...)` exposes read-only materialization source-drift reporting.
  - Dataset-wide update orchestration remains future work.

- M16 Data Manager recipe-collection update workflow is accepted:
  - D1 added `DataManagerUpdateService`, `DataManagerUpdatePlan`, items, actions, and blockers for read-only recipe-collection update planning.
  - D2 added `execute_update_plan(...)` for controlled selected-action and all-actionable execution from an existing plan.
  - D3 added the Data Manager `Plan Updates...` recipe-collection UI entry point, update-plan dialog, execution report display, and post-execution saved-artifact / Analysis Database refresh.
  - D4 was a validation-only release-readiness pass with no code, test, or documentation changes.
  - Plans map `ArtifactRecoveryPlanner` statuses into update items/actions/blockers and include linked Analysis Database materialization source-drift checks when `source_database_id` is present.
  - Artifact regeneration remains delegated through `ArtifactRecoveryRegenerator` / `ArtifactRecipeExecutor` / `ArtifactCalculationService`.
  - Linked Analysis Database rebuild remains delegated through `ArtifactRecoveryDatabaseRebuilder` / `AnalysisDatabaseStore`, and rebuild actions depend on planned artifact regeneration actions.
  - GUI displays service-produced plan/report data and does not parse `source_ohlcv.snapshot` or classify source drift.
  - Dataset-wide scanning, arbitrary dependency graph inference, background task/progress integration, and broader Update Manager entry points remain future work.

- DMU selected artifact/database update workflow is accepted:
  - DMU2 added `DataManagerSelectedUpdateService` with `plan_artifact_updates(...)`, `execute_artifact_update_plan(...)`, `plan_database_updates(...)`, and `execute_database_update_plan(...)`.
  - The service plans saved indicator, oscillator, construct, and Analysis Database update status without GUI-owned classification.
  - `OLD` means known stale/source-drifted and actionable; unknown or legacy lineage is not treated as OLD by default.
  - Draft Analysis Databases classify as DRAFT, not OLD.
  - Selected artifact execution delegates through existing recovery/regeneration/calculation ownership.
  - Selected database execution rebuilds existing materialized databases through Analysis Database store/materialization ownership while preserving identity, display name, manifest recipe, feature sources, feature columns, and component list.
  - DMU3 added Saved Indicators / Oscillators / Constructs controls for `Select All`, `Deselect All`, `Check Update`, and `Update Selected Artifacts`.
  - DMU3 added Database Builder controls for `Select All`, `Deselect All`, `Check Update`, and `Update Selected Databases`.
  - Check Update is read-only; Update Selected acts only on checked OLD/actionable items from the latest plan.
  - Selected update dialogs provide preflight, synchronous running state, and terminal report without fake mid-operation cancellation.
  - Raw OHLCV update/repair/acceptance remains Download Manager / OHLCV Maintenance.

- DMCB Data Manager Construct Batch Builder workflow is accepted:
  - DMCB1 added the Data Manager-only `Construct Batch...` entry point from Calculate and Save Tool Outputs when Constructs are selected, and sized the Data Manager financial-tools popup at 60% usable screen width and height while preserving minimum-size intent.
  - DMCB2 added `DataManagerConstructBatchPlanner` with `plan_unary_batch(...)`, `plan_delta_batch(...)`, and `plan_from_intent(...)` for read-only batch planning.
  - Supported generic batch constructs are unary `derivative`, `angle`, `percent_span_angle`, `angle_momentum`, and binary `delta` with `delta = minuend - subtrahend` reporting.
  - Generic batch excludes `braids`, `braid_instability`, `trap_area`, and `dynamic_binning`; topology-template and grouped-analysis workflows remain future/special-case work.
  - Planning uses saved artifact metadata, `selectable` / `analysis_usable` eligibility, timestamp-safe alignment/common-range checks, expected recipe/output preview, and read-only existing-recipe detection. Equal row count alone is not alignment proof.
  - DMCB3 added `DataManagerConstructBatchPersistenceService` for saving selected planned recipes through `ArtifactRecipeStore`, reusing existing recipes, and optionally saving ordered recipe collections through `ArtifactRecipeCollectionStore`.
  - DMCB4 wired the GUI to Preview Plan, Save Recipes, and Save as Collection. Blocked/error items cannot be persisted, existing_recipe items can be reused, and cross-widget selected saved artifact column handoff remains postponed until a clean selection bridge exists.
  - DMCB5 added `DataManagerConstructBatchExecutionService` and enabled Calculate Artifacts after a valid plan with selected persistable items.
  - Calculation persists/reuses selected recipes first, then executes saved/reused recipes sequentially through `ArtifactRecipeExecutor` / `ArtifactCalculationService`.
  - The GUI displays preflight/running/terminal reports and refreshes saved artifact lists, but it does not directly write CSV or sidecar files and does not calculate artifacts directly.
  - Construct Batch does not create, extend, build, rebuild, or materialize Analysis Databases, and raw OHLCV update/repair/acceptance remains Download Manager / OHLCV Maintenance.

- M17 Study Environment recipe-to-database workflow is accepted:
  - Historical saved studies now carry `StudyUserMetadata` with `important`, `description`, and `dataset_role`.
  - RS7 supersedes the earlier visible chart-row/header metadata action placement. Per-study metadata is now selected while saving or updating a Study Environment.
  - Study metadata is semantic/user-facing context only; it does not affect computation, rendering, style, runtime state, artifact identity, recipe identity, or geography truth.
  - Study serialization, Study Environments, and Workspace Snapshots preserve `user_metadata`, with backward-compatible defaults for older payloads.
  - `StudySetupRecipeExportPlanner` provides read-only Study Environment to recipe export planning with important-only filtering, exportable / conditional / blocked / skipped classification, recipe payload previews, and collection draft previews.
  - `StudySetupRecipeExportPersistenceService` persists selected/all exportable plan candidates as recipes and optional ordered recipe collections through the recipe stores.
  - Data Manager exposes `Create Recipes from Study Environment...` for previewing plans, selecting exportable candidates, saving recipes, optionally saving collections, and viewing persistence reports.
  - `AnalysisDatasetGeographyPolicy` reports OHLC base, explicit Volume artifact, Braids, Peaks & Troughs, UTC / Universal Trend Classifier, raw OHLCV volume, semantic volume duplication risk, and `dataset_role` mismatch warnings without enforcing geography.
  - `RecipeCollectionDatabasePlanner` resolves only current/up-to-date recipe-collection artifacts into Analysis Database source/column previews and blocks missing, stale, source-drifted, freshness-unknown, blocked, duplicate-column, and cross-market cases.
  - `AnalysisDatabaseStore.save_manifest(...)` now ensures the target manifest directory exists before atomic JSON writes and uses shorter `adb_` / `adf_` atomic temp prefixes.
  - `RecipeCollectionDatabaseService` retains data-layer draft-manifest construction for compatibility and extends existing manifests from C2 plans through existing store/editor ownership, without materializing `dataframe.csv`.
  - Data Manager exposes `Extend Database from Collection...` in the selected Analysis Database workflow for viewing C2 plans/geography reports and invoking C3 extension after confirmation.
  - Database seed creator remains the only user-facing Analysis Database creation workflow; saved recipe collection controls no longer expose a database create/extend action.
  - Missing/stale artifacts remain handled through the existing `Plan Updates...` workflow; C4 does not run update execution, calculate artifacts, execute recipes, or materialize databases.

- M18 Study Environment / Workspace Snapshot / Notebook update workflow is accepted:
  - Study Environment saves support Save as new and Update existing modes; Save as new remains the default.
  - Workspace Snapshot saves support Save as new and Update existing modes; Save as new remains the default.
  - Update existing requires selecting an existing saved item, preloads name/description, reuses the existing `setup_id` or `snapshot_id`, preserves `created_at_ms`, advances `updated_at_ms`, recomputes `content_hash`, and does not create duplicate files.
  - `ChartStudySetupStore.update_setup(...)`, `HistoricalWorkspaceSnapshotStore.update_snapshot(...)`, and `HistoricalNotebookStore.update_notebook(...)` own update persistence.
  - Workspace Snapshot update preserves existing `notebook_ref` behavior.
  - Notebook Save as new creates a distinct notebook identity without repointing existing Workspace Snapshot `notebook_ref` values.

- M19 Research Suite RS1-RS4 workflow is accepted:
  - Research Suite is the user-facing name for the historical chart research/design area; internal names such as `HistoricalDataManagerWindow`, `ChartStudySetup`, `StudySetupRecipeExportPlanner`, schema fields, IDs, and store paths remain stable.
  - Research Suite artifact save saves or reuses the corresponding reproducible recipe in the Data Manager-visible `ArtifactRecipeStore(historical_root=...)` before artifact persistence continues.
  - Artifact sidecars record `recipe_id`, `recipe_hash`, and `recipe_hash_short` as non-identity recipe metadata.
  - Study application remains chart-local and non-persistent.
  - Saving a Study Environment or Workspace Snapshot does not directly persist recipes.
  - `StudyEnvironmentManagerDialog` lists saved Study Environments, shows contained studies, edits top-level details, edits per-study serialized `user_metadata`, and deletes through `ChartStudySetupStore` APIs.
  - `WorkspaceSnapshotManagerDialog` lists saved Workspace Snapshots, shows saved charts/studies and `notebook_ref`, edits top-level details, and deletes through `HistoricalWorkspaceSnapshotStore` APIs.
  - Embedded Workspace Snapshot study metadata is read-only in RS4.
  - No recipe creation, artifact calculation, Workspace Snapshot export, assigned-notebook deletion, or Analysis Database creation is part of those dialogs.

- M20 Research Suite notebook UX RS5 workflow is accepted:
  - Notebook editor dirty tracking covers name, description, table edits, combo edits, row add/delete, chart tab deletion, annotation offsets, and chart refresh payload changes.
  - Dirty notebooks prompt with Save / Don't Save / Cancel before close, Create New Notebook, Load Notebook, assigned notebook replacement, or Workspace Snapshot assigned-notebook replacement.
  - Save proceeds only when the existing save flow succeeds; Don't Save proceeds without writing; Cancel aborts the close/load/replace action.
  - Notebook formatting palettes sit beside Add Note, Add Trade, and Add Point of Interest.
  - Free-text formatting supports bold, underline, text color, bullet list, and numbered list for notebook description, note text, trade note text, POI title, and POI description.
  - Plain fields remain populated and formatted content may be stored in optional parallel HTML fields such as `description_html`, `note_html`, and `title_html`.
  - Old plain-text notebooks remain loadable, and formatted HTML fields participate in notebook `content_hash` when present.
  - Notebook formatting does not change Study Environment, Workspace Snapshot, Data Manager, artifact, recipe, or database workflows.

- M21 Study Environment metadata placement cleanup is accepted:
  - Applied study overlay rows and oscillator pane headers no longer expose the visible metadata action.
  - Style, Edit, and Remove chart-study controls remain chart-local actions.
  - Save Study Environment / Update existing Study Environment includes a compact per-study metadata editor for `important`, `dataset_role`, and `description`.
  - Dialog-selected metadata is applied to cloned serialized study payloads before `ChartStudySetupStore` save/update.
  - The save dialog does not mutate the live chart registry because serialized save payloads do not contain durable chart-session instance IDs.
  - Study Environment Manager remains the post-save editor for saved serialized `user_metadata`.
  - Study metadata semantics, computation, rendering, style, Workspace Snapshot behavior, Notebook behavior, artifact/recipe behavior, and Data Manager workflows are unchanged.

- M22 Financial Tools Apply preflight/progress is accepted:
  - Financial Tools Apply opens a chart-panel-owned preflight/progress dialog before controller execution.
  - The dialog shows tool title, chart/dataset context, `Input bars to process: N`, progress/status text, and dialog-visible errors.
  - It supports pre-execution cancel; once synchronous Apply starts, progress is indeterminate and Cancel is disabled.
  - Existing controller calculation, `apply_succeeded`, panel success handling, workspace series application, and `ChartStudyRegistry.add(...)` registration remain the path.
  - Financial Tools calculation semantics and chart-local/non-persistent behavior are unchanged.
  - Study Environment, Workspace Snapshot, Notebook, Data Manager, and Analysis Database workflows are unchanged.

- Post-smoke DM3/DM2/RS8/RS9/RS10/DL1 corrections are accepted:
  - DM3 moved collection-based Analysis Database extension into the selected Analysis Database workflow through `Extend Database from Collection...`, kept C2 preview/confirm/C3 extension boundaries, and left Database seed creator as the only user-facing creation path.
  - DM2 improved Data Manager dialog/button readability and changed already-present Saved Artifact Columns to light green `#C8F7C5`, black foreground, and bold font without changing component semantics.
  - RS8 added Style editor Apply so current style commits to the live chart without closing; OK applies and closes; Cancel does not apply further unapplied edits or roll back committed Apply changes.
  - RS9 refreshes the notebook indicator immediately after notebook assignment/unassignment for the current workspace snapshot without reloading the workspace.
  - RS10 added Workspace Snapshot load preflight/loading with snapshot summary, notebook assignment display, replacement warning, indeterminate synchronous loading state, and preserved dirty-notebook confirmation.
  - Restore remains synchronous, non-cancellable after it starts, and non-transactional.
  - DL1 throttles/coalesces Download Manager progress display in the GUI layer while preserving final progress flushes and downloader/provider/OHLCV persistence semantics.
  - Final smoke remains pending for the broader post-smoke correction set.

Next direction:

- Treat the current Historical Download Manager M7/M13 behavior as the accepted OHLCV ingestion and preliminary-validation baseline.
- Treat OHLCV Maintenance as the explicit acceptance workflow for OHLCV validation, repair, source-invalid handling, source correction, and modified status.
- Treat the current Research Suite chart/study M8 behavior plus M12 chart artifact hardening and M19 artifact-save recipe invariant as the accepted chart-session and artifact-calculation baseline.
- Treat the current Data Manager M4/M5/M6 behavior plus M13 loadability gates, M14 source OHLCV provenance snapshots, M15 source-drift classification, M16 recipe-collection update workflow, M17 Study Environment recipe export / selected-database recipe-collection extension, and DMU selected artifact/database update workflow as the accepted analysis-database baseline.
- Integrate GUI release checks into CI/build packaging so shipped archives exclude `.git`, `.pytest_cache`, `__pycache__`, and `.pyc` files and preserve Data Manager ownership boundaries.
- Design broader Data Manager update expansion for dataset-wide scanning using the existing provenance, recovery, update-plan, regenerator, rebuilder, and store services without moving classification into GUI.
- Consider background task/progress integration for long update executions, while preserving explicit user confirmation and data-layer ownership.
- Consider arbitrary dependency graph inference only as a future expansion beyond recipe collection order.
- Consider deeper recipe freshness enforcement as future work; artifact sidecars already record non-identity recipe metadata from RS1.
- A partition-level artifact index may later cache summaries for faster listing/search, while sidecars remain the metadata source of truth.

------------------------------------------------------------
6) FINANCIAL TOOLS
------------------------------------------------------------

Current accepted updates:

- ARSI now follows the Ultimate RSI-style two-line model: main ARSI output plus signal/mean output.
- ARSI public params include `period`, `method`, `signal_period`, and `signal_method`.
- Supported ARSI smoothing methods are `EMA`, `SMA`, `RMA`, and `TMA`.
- ARSI output names are `arsi_{period}_{method}` and `arsi_signal_{period}_{method}_{signal_period}_{signal_method}`.
- Volume is accepted as an oscillator with raw histogram output and configurable rolling mean output.
- Oscillator naming/spec/contract validation remains required after any public output change.
- GUI colors and widths remain chart-local style defaults, not financial-tool runtime truth.

------------------------------------------------------------
7) BACKTESTING + SIMULATION
------------------------------------------------------------

[UNCHANGED]

------------------------------------------------------------
8) USER POLICY
------------------------------------------------------------

[UNCHANGED]

------------------------------------------------------------
9) SECURITY
------------------------------------------------------------

[UNCHANGED]

------------------------------------------------------------
10) OBSERVABILITY
------------------------------------------------------------

[UNCHANGED]

------------------------------------------------------------
11) INSTALLER + DEPENDENCIES
------------------------------------------------------------

[UNCHANGED]

------------------------------------------------------------
Cross-cutting principles
------------------------------------------------------------

Boundary rule: GUI ↔ Engine ↔ Core subsystems
Auditability: reproducible recommendation fingerprint
Failure-first design
Security hygiene

------------------------------------------------------------
V1 Milestones (initial target)
------------------------------------------------------------

(unchanged — still valid baseline)

------------------------------------------------------------
Change log
------------------------------------------------------------
v0.36: Analysis Suite target preview planner AS5 sync. Documents `AnalysisSuiteTargetPlanner`, `AnalysisSuiteTargetDefinition`, and `AnalysisSuiteTargetPreviewReport`; target versus label semantics; future return regression; future direction classification; positive `horizon_bars` alignment; last-N unavailable rows; AS1 `can_preview` gating; JSON-safe reports; and leakage metadata marking outputs as `target_only`, `future_derived`, and non-feature-eligible. Target/label persistence, GUI wiring, projects/runs/reports, models, signals, trading logic, artifact calculation, recipe execution, OHLCV repair, and Analysis Database mutation remain out of scope.

v0.35: Analysis Suite bounded preview AS4 sync. Documents `AnalysisSuiteDataframePreviewService`, Head/Tail preview in `AnalysisSuiteWindow`, AS1 `can_preview` gating, service-enforced default `100` / max `500` row limits, JSON-safe rows, timestamp display fields, and unchanged read-only/no-mutation/project/run/model/signal boundaries.

v0.34: Analysis Suite read-only catalog AS2 sync. Documents `AnalysisSuiteWindow`, the `Analysis -> Analysis Suite` menu action, preserved `Analysis -> Data Manager` separation, AS1 readiness-report consumption, read-only catalog/details behavior, Data Manager routing, postponed bounded dataframe preview, and unchanged database/artifact/OHLCV/project/run/model/signal boundaries.

v0.33: Analysis Suite dataset readiness AS1 sync. Documents the read-only `AnalysisSuiteDatasetReadinessService`, readiness/catalog reports, strict-ready policy, minimum topology requirements, corrupt manifest/dataframe/source-drift diagnostics, and unchanged Data Manager/OHLCV boundaries. Analysis Projects/Runs/Reports, model logic, artifact calculation, database rebuild/materialization, and OHLCV repair remain out of scope.

v0.32: Data Manager Construct Batch Builder sync. Documents DMCB1-DMCB5: Data Manager-only construct batch popup/button behavior, read-only planner preview, recipe persistence, optional ordered collection persistence, artifact calculation through existing recipe execution/calculation ownership, supported unary/delta constructs, excluded topology-template/grouped-analysis constructs, timestamp-safe alignment rules, and unchanged Analysis Database/raw-OHLCV/Research Suite boundaries.

v0.31: Data Manager selected update sync. Documents DMU1 60% usable-screen-width Data Manager dialogs, DMU2 `DataManagerSelectedUpdateService`, DMU3 selected artifact/database `Check Update` and `Update Selected...` controls, OLD/DRAFT semantics, synchronous selected-update reports, and unchanged raw-OHLCV/recipe-collection ownership boundaries. Final smoke remains pending.

v0.30: Post-smoke correction sync. Documents DM3 selected-database-only collection extension, DM2 Data Manager readability/highlight polish, RS8 Style editor Apply semantics, RS9 notebook indicator refresh, RS10 Workspace Snapshot load preflight/loading, and DL1 Download Manager GUI-layer progress throttling. Final smoke remains pending.

v0.29: Financial Tools Apply preflight sync. Documents the chart-panel preflight/progress dialog, `Input bars to process: N`, pre-execution cancel, indeterminate progress during synchronous Apply, dialog-visible success/failure completion, preserved controller/panel study-registration path, and unchanged chart-local/non-persistent boundaries.

v0.28: Study Environment metadata placement RS7 sync. Documents removal of the chart-row/header metadata action placement, Save/Update Study Environment per-study metadata controls, serialized payload writeback, Study Environment Manager post-save editing, and unchanged live chart registry/Data Manager behavior.

v0.27: Research Suite notebook UX RS5 sync. Documents notebook dirty-state tracking, Save / Don't Save / Cancel close/replace behavior, rich-text formatting palettes for notebook free-text fields, plain-text compatibility, optional parallel HTML fields, and unchanged Study Environment / Workspace Snapshot / Data Manager boundaries.

v0.26: Research Suite RS1-RS4 sync. Documents Research Suite user-facing terminology, artifact save recipe persistence in the Data Manager-visible recipe store, artifact sidecar recipe metadata, Notebook Save as new / Update existing, and saved Study Environment / Workspace Snapshot management dialogs. Embedded Workspace Snapshot study metadata is read-only in RS4. No recipe creation, artifact calculation, or Analysis Database creation is part of those dialogs.

v0.25: Historical Study metadata action and preset update workflow. Documents the earlier chart-local metadata action baseline plus Save as new / Update existing modes for Study Environments and Workspace Snapshots. RS7 supersedes the chart-row/header metadata placement with Save/Update Study Environment metadata controls.

v0.24: Historical Study recipe-to-database workflow. Documents StudyUserMetadata, chart-local Study Metadata editing/persistence, Study Environment to recipe export planning/persistence/UI, diagnostic AnalysisDatasetGeographyPolicy, recipe-collection artifact resolution planning, AnalysisDatabaseStore manifest directory guard and short temp prefixes, and RecipeCollectionDatabaseService data-layer draft/extend behavior. DM3 later superseded the user-facing workflow with selected-database-only collection extension. Artifact calculation, recipe execution, Plan Updates execution, database materialization, hard geography enforcement, Workspace Snapshot export to recipes, notebook loading, dataset-wide scanning, arbitrary dependency inference, and background update progress remain out of scope.

v0.23: Data Manager recipe-collection update workflow. Documents D1-D4 implementation: read-only update planning, controlled selected/all actionable execution, recipe-collection `Plan Updates...` UI, execution reports, linked Analysis Database rebuild planning/execution through existing services, post-execution refresh, and validation-only D4. Dataset-wide scanning, arbitrary dependency inference, background task/progress integration, and broader Update Manager entry points remain future work.

v0.22: Recovery source-drift classification. Documents Patch C2 implementation: source OHLCV snapshot comparison helpers, ArtifactRecoveryPlanner source-drift classification, legacy missing snapshot compatibility, blocked current-OHLCV actionability behavior, existing recovery execution delegation, and AnalysisDatabaseStore read-only materialization source-drift reporting. Recipe-collection update workflow was added later in v0.23.

v0.21: Data Manager source OHLCV lineage hardening. Documents Patch C implementation: derived artifact sidecars and Analysis Database materialization metadata now record `source_ohlcv.snapshot` with source dataset identity, validation status, fingerprints, capture timestamp, and source-correction provenance. Rebuild refreshes materialization source provenance. Recovery/source-drift classification was added later in v0.22.

v0.20: OHLCV acceptance and loadability sync. Documents Download Manager preliminary validation with default unknown/not_validated metadata, OHLCV Maintenance validation/repair/source-correction workflow, `modified` status, ok/modified loadability policy, Research Suite chart load gating, Data Manager Patch A/B gates and selector messaging, and the pre-M14 Data Manager source-OHLCV lineage gap.

v0.19: Historical apply/save/recovery hardening. Documents Historical Download command-boundary cleanup, TaskManager terminal cleanup, timeline-first runtime projection alignment, sidecar-driven saved-source selection, shared `result_to_save_dataframe(...)` save conversion, shared UTC dependency preparation, and recovery planner UTC dependency-intent parity with read-only join-key blocker checks.

v0.18: Core-boundary repair and exchange-registry baseline. Documents normalized audit event handling, implemented HistoricalDatasetService cache invalidation APIs, downloader post-write dataset-cache invalidation, pyproject runtime dependency truth, and the minimal Core `ExchangeRegistry` capability provider used by CoreBridge and HistoricalDownloader while keeping Bybit as the only default adapter.

v0.17: Notebook / preset delete / Pan Anchor polish. Documents Notebook Manager assignment/delete ownership, Notes/Potential Trades/POI final row layouts, Potential Trades Long/Short runtime markers, annotation offset persistence, confirmed saved Study Environment and Workspace Snapshot deletion, maximized Research Suite opening, and off-by-default Pan Anchor horizontal timestamp-based pan synchronization. Later RS5 documentation supersedes the old close-save wording with dirty-state Save / Don't Save / Cancel behavior.

v0.16: Notebook and Workspace Snapshot integration. Documents NotebookStore persistence, Notes menu actions, save/load/assign Notebook workflows, Workspace Snapshot `notebook_ref`, dataset-keyed notebook chart tabs, structured Notes/Trades/POI rows, row-level Go To buttons, runtime POI chart markers, and the Open Notebook quick action. Study Environments remain notebook-free and POI markers remain runtime chart annotations rather than hidden studies.

v0.15: Oscillator styling, ARSI upgrade, and historical workspace compact layout. Documents Volume histogram/mean behavior, threshold-aware oscillator segment splitting, dynamic oscillator default-style resolution, Ultimate RSI-style ARSI with orange signal/mean line and 80/50/20 guides, compact chart workspace spacing, Window-menu view mode controls, and current-mode menu-bar label.

v0.14: Historical chart/study hardening. Documents Core-backed dataset catalog selection, GUI-thread/stale-result guards for dataset open and slicing, renderability/analysis-source separation, explicit save metadata, construct saved-identity hashes, public render-cache invalidation, Sequence-safe series values, dataset-service cache invalidation, and full uploaded test validation.


v0.13: Historical Download Manager hardening and exchange capability ownership. Documents adapter-owned market/timeframe/alias/interval/limit truth, Core-owned preflight planning, multi-timeframe task monitoring, Stop/Cancel routing through Core/TaskManager, adapter-default page limits with max clamping, and neutral validation for fixed canonical timeframes.

v0.12: Data Manager M6F visual baseline. Documents the maximized compact layout, contextual button placement, DataFrame Preview header polish, equal Database Builder list/details display space, enlarged local font, and bold widget titles while preserving existing Data Manager ownership semantics.

v0.11: Data Manager / Analysis Database workflow hardening. Added dataset-prefix database names, no-whitespace validation, duplicate visible-name rejection, checkbox-based Database Builder selection, and store-owned build/rename/delete behavior.

v0.10: Data Manager and artifact metadata baseline. Added Analysis Database workflow, CSV + `.meta.json` sidecar policy for OHLCV and derived artifacts, and restore-only metadata backfill as a maintenance layer.

v0.9: GUI chart stack hardening (contract-first surfaces, volume refresh normalization, release packaging guardrails)

v0.1: Initial roadmap
v0.2: Introduced runtime state + dataset architecture
v0.3: Implemented StateStore, task lifecycle, service lifecycle, audit integration
v0.4:

Explicit service registration model (lifecycle vs capability separation)
Registry restricted to runtime payloads only
Active-only task runtime retention
Centralized runtime audit event construction

v0.5:

Connection runtime state introduced
Feed-level connection lifecycle tracking implemented
Session runtime state (minimal surface) introduced
Adapter / runtime boundary clarified
Runtime connection visibility integrated with audit system

v0.6:

Explicit CoreBridge-owned realtime control boundary introduced
MainWindow direct feed orchestration removed
Realtime GUI behavior aligned with bridge signals and runtime truth
Temporary realtime stop behavior clarified for the current GUI test harness



v0.7:

Phase 5 — GUI Visibility Layer completed

Introduced centralized Runtime Inspector window
Provides tabbed visibility into:
- application runtime state
- connection lifecycle state
- active tasks
- tracked windows
- recent audit events

GUI remains a read-only observer of runtime state
Polling-based snapshot model retained (no signal redesign)
No changes to Core runtime semantics or StateStore

Improved system observability without introducing:
- event bus
- orchestration engine
- connection manager subsystem

Established a clear separation:
Core → authoritative runtime + audit
GUI → structured visualization layer



Explicit CoreBridge-owned realtime control boundary introduced
MainWindow direct feed orchestration removed
Realtime GUI behavior aligned with bridge signals and runtime truth
Temporary realtime stop behavior clarified for the current GUI test harness
---

## v0.8 — Refactor Freeze Baseline — 2026-04-20
Completed architecture-hardening refactor pass:

- Financial tools split into contract-backed bridge/runtime architecture.
- `ft_naming.py` and `ft_specs.py` remain public façades over `naming_runtime` and `specs_runtime`.
- Indicators, oscillators, and constructs use family-local runtime modules behind stable bridge classes.
- Core Bybit feed boundary no longer imports GUI bridge classes.
- `HistoricalDatasetService` exposes explicit public timeline, columns, and full-dataframe APIs.
- Historical chart controller split into controller-owned helper package while preserving public import.
- Workspace split into private `_workspace` helpers while preserving `workspace.py` public façade.
- Panes moved into a public `panes/` package.
- Renderers split into `chart/rendering/` helpers while preserving public render surface classes.
- Historical chart panel split into private `_historical_chart_panel` helpers while preserving `historical_chart_panel.py` public façade.
- Autoscale is explicitly workspace-owned price-pane vertical fit state; viewport remains horizontal camera only.

Next production priorities:

1. live GUI smoke-test the refactored chart stack;
2. add contract tests for viewport pan/zoom and workspace Autoscale/manual-y;
3. add import-boundary tests for Core↔GUI and financial-tools runtime/spec/naming layers;
4. integrate release packaging guardrails (static checks + clean zip) into CI/build so shipped archives exclude `.git`, `.pytest_cache`, `__pycache__`, and `.pyc` files;
5. declare runtime dependencies in packaging metadata.

UTC / Peaks & Troughs historical integration completed:
- historical UTC uses controller-injected Peaks & Troughs columns rather than owning artifact loading;
- UTC now supports independent trend and horizontal-range fractal dependencies, with controller-side two-purpose injection and deduplicated artifact-column merging;
- directional trend detection is sequential swing-state logic, not full vectorization;
- horizontal range detection uses sequential historical replay, separate range-fractal discovery, configurable break modes, and pending breakout/reclaim handling;
- structural continuation and shared-extreme reversal rules are now part of UTC's historical behavior;
- historical directional trend detection preserves data-gap honesty by preventing intervals from bridging invalid OHLC/source rows;
- rendering remains unchanged and consumes upstream state intervals.
