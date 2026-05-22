🧠 Leonardo — Roadmap

Version: v0.19
Status: Living document (expected to change)
Updated: 2026-05-22

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
- `Database seed creator` creates named database seeds with dataset-prefix defaults such as `BTCUSDT_30m_`, no-whitespace validation, and same-market duplicate-name rejection.
- Checked saved artifact columns feed the `Database seed creator` only; they do not feed Database Builder.
- Saved artifact column discovery is shared through a GUI-owned loader so the main selector, build dialog, and component editor use the same artifact listing behavior.
- `Database Builder` supports exactly-one checked database selection for separate build, rebuild, component edit, rename, delete, and preview actions.
- `Build Selected Database` opens a dedicated build dialog that auto-loads saved artifacts, highlights already-present components, and materializes the selected database from its existing saved manifest recipe.
- `Rebuild Selected Database` rewrites `dataframe.csv` for a materialized database from the same saved manifest recipe.
- Build/rebuild preserves `database_id`, folder, display name, feature sources, feature columns, and recipe hash; it does not add, remove, or replace artifact components.
- `Edit Selected Database Components...` is the explicit workflow for add/remove/replace component changes. It auto-loads saved artifacts, highlights already-present components, updates the saved recipe through the data-layer component editor, resets materialization to draft, and requires a later build.
- Analysis Database rename preserves immutable `database_id`; delete removes the folder-backed artifact.
- Duplicate visible-name validation applies to draft creation and rename, not to build/rebuild of an existing database by `database_id`.
- Data Manager opens maximized and uses the accepted M6F compact visual layout: Dataset and Calculate and Save Tool Outputs on the top row, DataFrame Preview and Saved Indicators / Oscillators / Constructs on the middle row, Data Checks / Metadata Tools plus Database seed creator on the lower-left area, and Database Builder on the lower-right area.
- Main Data Manager widgets use the shared right-side button rack for actions.
- DataFrame Preview keeps source, row-limit, and visible timestamp information in the content header while its action remains in the shared button rack.
- Saved artifact actions and Database Builder actions use the shared button rack so lists and details retain content width.
- Data Manager-local text is enlarged and widget titles are bold while normal labels/buttons remain normal weight.
- Saved Artifact Recipes and Saved Recipe Collections dialogs now use larger/readable list areas for long names.
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

- M10 Historical Notebook / Workspace Snapshot integration is accepted:
  - Historical Data Manager exposes `Notes` menu actions for creating, opening, saving, loading, and managing notebooks.
  - `HistoricalNotebookStore` persists notebook JSON under `chart_presets/notebooks` while `HistoricalNotebookWindow` remains an in-memory editor.
  - Workspace Snapshots store only optional `notebook_ref` metadata and never embed notebook content.
  - Notebook chart tabs are keyed by dataset identity, not by chart position.
  - Notes, Potential Trades, and Points of Interest use structured rows with explicit delete/navigation behavior.
  - POI rows and eligible Potential Trades rows can produce runtime chart markers; those markers are notebook annotations, not hidden studies or financial-tool outputs.
  - The menu-bar quick actions include an `Open Notebook` / `Notebook` button before Study Setup actions when an assigned notebook is available.

- M11 Historical Notebook / preset delete / Pan Anchor polish is accepted:
  - Notebook Manager owns notebook assignment/unassignment, assignment summaries, descriptions/last-save visibility, and confirmed notebook deletion.
  - Notebook assignment truth remains only in Workspace Snapshot `notebook_ref`; notebook files do not store assigned-workspace truth.
  - Notes rows no longer navigate; Potential Trades rows have explicit `Go`, `Delete`, empty-by-default `Direction`, and Long/Short marker semantics.
  - Potential Trade Long markers render as green upward arrows below bars; Potential Trade Short markers render as red downward arrows above bars.
  - Notebook JSON persists additive `annotation_settings` for POI, PT Long, and PT Short marker offsets.
  - Notebooks auto-save on close through the Historical Data Manager/store boundary.
  - Load Study Setup and Load Workspace Snapshot dialogs expose confirmed Delete actions; Workspace Snapshot deletion does not delete referenced notebooks.
  - Historical Data Manager opens maximized.
  - Pan Anchor is accepted as an off-by-default, horizontal-only, timestamp-center pan synchronization mode across active charts in the same Historical Data Manager.

- M12 Historical apply/save/recovery hardening is accepted:
  - Historical Download command boundary cleanup moved downloader request/root construction behind CoreBridge while the GUI passes plain intent and observes audit/task state.
  - TaskManager terminal cleanup removes completed, failed, and cancelled tasks from its active internal task map while preserving terminal history in audit.
  - Historical runtime projection now prefers explicit `ts_ms` / `time` / non-positional index alignment before the legacy full-dataset/no-timeline positional fallback.
  - Financial Tool Manager saved-source selection consumes saved artifact sidecar `selectable` / `analysis_usable` metadata as source-selection truth, with CSV-header fallback only for legacy or malformed sidecars.
  - Chart save and save-only artifact calculation share `result_to_save_dataframe(...)` so full-dataset saved values preserve timestamps, output order, boolean/state outputs, numeric values, and gaps consistently.
  - Historical UTC Peaks & Troughs dependency preparation is centralized in `utc_dependency_sources.py` for chart apply/save and `ArtifactCalculationService`, preserving trend/range intent, overrides, configured-root lookup, and deterministic `ts_ms` / `time` alignment.
  - ArtifactRecoveryPlanner shares UTC dependency-intent resolution, remains read-only, and blocks unsafe UTC dependencies with missing or duplicate join keys.
  - Consolidated historical validation passed the focused Core/download/chart/data/recovery suite and confirmed no new layering violations in the historical scope.

Next direction:

- Treat the current Historical Download Manager M7 behavior as the accepted OHLCV ingestion baseline.
- Treat the current historical chart/study M8 behavior plus M12 apply/save/recovery hardening as the accepted chart-session and artifact-calculation baseline.
- Treat the current Data Manager M4/M5/M6 behavior as the accepted analysis-database baseline.
- Integrate GUI release checks into CI/build packaging so shipped archives exclude `.git`, `.pytest_cache`, `__pycache__`, and `.pyc` files and preserve Data Manager ownership boundaries.
- Consider adding recipe-hash lineage into saved artifact sidecars in a future migration so recovery can prove exact recipe-hash freshness instead of metadata-level consistency only.
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
v0.19: Historical apply/save/recovery hardening. Documents Historical Download command-boundary cleanup, TaskManager terminal cleanup, timeline-first runtime projection alignment, sidecar-driven saved-source selection, shared `result_to_save_dataframe(...)` save conversion, shared UTC dependency preparation, and recovery planner UTC dependency-intent parity with read-only join-key blocker checks.

v0.18: Core-boundary repair and exchange-registry baseline. Documents normalized audit event handling, implemented HistoricalDatasetService cache invalidation APIs, downloader post-write dataset-cache invalidation, pyproject runtime dependency truth, and the minimal Core `ExchangeRegistry` capability provider used by CoreBridge and HistoricalDownloader while keeping Bybit as the only default adapter.

v0.17: Historical Notebook / preset delete / Pan Anchor polish. Documents Notebook Manager assignment/delete ownership, Notes/Potential Trades/POI final row layouts, Potential Trades Long/Short runtime markers, annotation offset persistence, notebook auto-save-on-close, confirmed saved Study Setup and Workspace Snapshot deletion, maximized Historical Data Manager opening, and off-by-default Pan Anchor horizontal timestamp-based pan synchronization.

v0.16: Historical Notebook and Workspace Snapshot integration. Documents NotebookStore persistence, Notes menu actions, Save/Load/Assign Notebook workflows, Workspace Snapshot `notebook_ref`, dataset-keyed notebook chart tabs, structured Notes/Trades/POI rows, row-level Go To buttons, runtime POI chart markers, and the Open Notebook quick action. Study Setup remains notebook-free and POI markers remain runtime chart annotations rather than hidden studies.

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
