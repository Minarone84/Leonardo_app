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

## Current Data Manager / Analysis Database workflow — 2026-05-25

Data Manager remains dataset/artifact oriented and separate from chart sessions. The current Analysis Database workflow includes:

- dataset selection through the CoreBridge/data-layer loadable OHLCV catalog, listing only `ok` and `modified` datasets and labeling modified datasets with `(Modified)`;
- no-loadable-dataset guidance that directs users to Historical -> OHLCV Maintenance;
- OHLCV preview verifies loadability through CoreBridge and uses the data-layer `csv_path` from the loadability report before bounded preview;
- `Database seed creator` for named draft manifests with a `SYMBOL_timeframe_` default prefix;
- checked saved artifact columns feed the `Database seed creator` only;
- no-whitespace, no-path-separator, same-market duplicate visible-name rejection for draft creation and rename;
- `Database Builder` for exactly-one-checkbox database selection, separate build and rebuild actions, explicit component editing, rename, delete, and preview;
- immutable `database_id` folder identity and mutable user-facing `display_name`;
- `Build Selected Database` opens a dedicated build dialog that auto-loads saved indicator, oscillator, and construct columns for visibility, highlights already-present database components, and materializes `dataframe.csv` from the selected database's saved manifest recipe without changing that recipe;
- `Rebuild Selected Database` rewrites `dataframe.csv` for an already materialized database from the same saved manifest recipe, preserving the same `database_id`, folder, display name, feature sources, feature columns, and recipe hash;
- `Edit Selected Database Components...` is the only workflow that intentionally changes an existing database recipe; it opens a dedicated component editor, auto-loads saved artifacts, highlights already-present components, supports explicit add/remove/replace actions, resets materialization to draft, and requires a later build;
- duplicate visible-name validation applies to creating new database drafts and renaming databases, not to materializing/rebuilding an existing database by `database_id`;
- save-only financial-tool artifact recipes and ordered recipe collections for reproducible full-dataset artifact calculation;
- larger Saved Recipes and Saved Recipe Collections dialogs for readable long names;
- recipe-collection recovery controls for checking artifact status, regenerating planner-actionable missing/stale/unknown artifacts, and rebuilding a linked Analysis Database when the collection carries `source_database_id`;
- Data Manager opens maximized and uses the accepted compact M6F visual layout: Dataset and Calculate and Save Tool Outputs on the top row, DataFrame Preview and Saved Indicators / Oscillators / Constructs on the middle row, Data Checks / Metadata Tools plus Database seed creator on the lower-left area, and Database Builder on the lower-right area;
- Data Manager main widgets use the shared right-side `make_button_rack(...)` action layout;
- DataFrame Preview keeps source, row-limit, and visible timestamp information in the content header while its action remains in the shared button rack;
- saved artifact and Database Builder actions use the shared button rack so lists and details retain content width.

Data Manager only uses accepted OHLCV. The shared data-layer helpers `evaluate_ohlcv_dataset_loadability(...)`, `require_ohlcv_dataset_loadable(...)`, and `format_ohlcv_loadability_error(...)` enforce the same policy as `HistoricalDatasetService`: `ok` and `modified` are loadable; `unknown`, `not_validated`, `warning`, `error`, missing/unreadable metadata, metadata mismatch, missing CSV, and stale validation fingerprints are blocked. `ArtifactCalculationService._load_full_dataset_dataframe(...)`, `AnalysisDatabaseStore._load_selected_ohlcv_dataframe(...)`, and `ArtifactRecoveryPlanner._recalculation_blockers(...)` all enforce this before using source OHLCV.

GUI code collects user selections and presents dialogs. It must not manually rewrite `manifest.json`, move/delete `analysis_databases/{database_id}/`, invent persistence rules, classify artifact recovery state locally, duplicate OHLCV validation/loadability policy, or replace Analysis Database components during build/rebuild. Recovery UI actions are intent surfaces only: status classification belongs to `ArtifactRecoveryPlanner`, artifact regeneration belongs to `ArtifactRecoveryRegenerator` / `ArtifactRecipeExecutor`, and linked database materialization belongs to `ArtifactRecoveryDatabaseRebuilder` / `AnalysisDatabaseStore`.

Saved artifact source selection in chart/Data Manager workflows consumes `.meta.json` column metadata when available. Valid sidecar `selectable` / `analysis_usable` metadata is the source-selection truth; CSV-header fallback is retained only for legacy, missing, or malformed sidecars.

Data Manager metadata/lineage hardening is implemented for generated outputs. Derived artifact sidecars and Analysis Database materialization metadata record source OHLCV provenance under `source_ohlcv.snapshot`, including source dataset identity, CSV/metadata paths, validation status, quality status, validation fingerprint, current CSV fingerprint, capture timestamp, and source-correction provenance when applicable. Analysis Database rebuild refreshes the materialization source snapshot instead of preserving stale source metadata. Future recovery/source-drift classification can use this metadata, but recovery does not yet classify artifacts or databases as source-drifted from the snapshot.

## Current Historical Chart / Study workflow — 2026-05-25

The historical chart stack is now hardened around the ownership chain:

```text
Core dataset truth → controller/session truth → panel chart-local study truth → workspace pane/layout contracts → pane handoff → renderer execution
```

Accepted behavior includes:

- dataset selection is Core/data-backed through `HistoricalDatasetService` catalog APIs and `CoreBridge`, not GUI folder-walking;
- chart creation uses the loadable OHLCV catalog and only accepts `ok` or `modified` datasets; `HistoricalDatasetService.open_dataset(...)` enforces the final gate before loading;
- dataset-open and resident-slice async results are marshalled back to the GUI thread and guarded against stale dataset/open-generation/request results;
- controller apply keeps full-dataset compute truth separate from resident-local render truth;
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

M6/M6B completed release-check/test reconciliation and full uploaded test validation without production-code changes.

## Current Historical Data Manager / Workspace layout workflow — 2026-05-25

Historical chart sessions hosted by `HistoricalDataManagerWindow` now support an 8-slot embedded workspace without changing chart-session, controller, renderer, data, or financial-tool ownership. The Historical Data Manager opens maximized so the chart workspace is immediately usable.

Accepted workspace behavior includes:

- New Chart selection uses the CoreBridge/HistoricalDatasetService loadable catalog, shows only `ok` and `modified` OHLCV, labels modified datasets, and displays OHLCV Maintenance guidance when no validated datasets are available;
- blocked datasets cannot bypass the selector because `HistoricalDatasetService.open_dataset(...)` refuses non-loadable OHLCV before chart loading;
- up to 8 embedded historical chart panels;
- stable logical slot identity ordered as `1-2`, `3-4`, `5-6`, `7-8`;
- detached charts reserve their original slot and dock back into that same slot;
- chart-level Position controls can move a chart to another slot or swap with an occupied slot while protecting reserved detached slots;
- two visualization modes: `Scroll 4` for scrolling beyond the first four visible charts, and `Fit 8` for fitting all embedded charts into the usable workspace;
- a checkable `Pan Anchor` quick action, off by default, that synchronizes horizontal panning across active charts in the same Historical Data Manager using timestamp-center recentering;
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

## Current Historical Notebook / Workspace Snapshot workflow — 2026-05-22

Historical Data Manager now includes a workspace-linked Historical Notebook workflow for chart analysis notes and runtime chart annotations.

Accepted notebook behavior includes:

- `Notes` menu actions for creating, opening, saving, loading notebooks, and opening `Notebook Manager...`;
- Notebook Manager owns assignment/unassignment, notebook descriptions/last-save visibility, assigned-workspace summaries, and confirmed notebook deletion;
- notebook persistence through `NotebookStore` under `chart_presets/notebooks`, outside the notebook window itself;
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
- notebooks auto-save on close through the existing Historical Data Manager / store boundary;
- a compact menu-bar `Notebook` quick action before the Study Setup actions opens the notebook assigned to the current workspace snapshot when a valid `notebook_ref` is available.

Study Setups remain notebook-free. Notebook data belongs to the notebook store and Workspace Snapshot association belongs to `notebook_ref` only.

## Current saved Study Setup / Workspace Snapshot delete workflow — 2026-05-22

Saved Study Setup and Workspace Snapshot load dialogs now expose confirmed Delete actions.

Accepted behavior includes:

- Load Study Setup can delete the selected saved setup through `ChartStudySetupStore.delete_setup(setup_id)`;
- deleting a saved Study Setup does not remove currently applied chart studies and does not affect Workspace Snapshots;
- Load Workspace Snapshot can delete the selected snapshot through `HistoricalWorkspaceSnapshotStore.delete_snapshot(snapshot_id)`;
- deleting a Workspace Snapshot does not delete referenced notebooks, datasets, saved studies, or saved artifacts;
- Workspace Snapshot delete confirmation explicitly mentions a referenced notebook when `notebook_ref` is present;
- delete dialogs refresh their list and clear stale selection/details after successful deletion.

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
