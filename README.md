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


## Current Historical Download Manager baseline — 2026-05-18

The Historical Download Manager is now a Core-supervised OHLCV ingestion flow. The GUI collects user input, displays exchange capabilities, requests preflight plans, shows the Confirm OHLCV Download dialog, opens the OHLCV Download Task monitor, and observes audit events. Core owns execution through TaskManager, HistoricalDownloader owns planning/paging/persistence/validation, and the exchange adapter owns venue-specific markets, timeframes, aliases, interval mappings, historical limits, and range-discovery behavior.

Important accepted behavior:

- multi-timeframe OHLCV selection and sequential batch execution;
- metadata-aware local file inspection and update-latest planning;
- preflight range discovery before confirmed download;
- task monitor progress, Stop/Cancel request handling, validation status, final recap, and batch validation summary;
- GUI `Limit = 0` means adapter/default page limit, and explicit values are clamped by the adapter maximum.

## Current Data Manager / Analysis Database workflow — 2026-05-16

Data Manager remains dataset/artifact oriented and separate from chart sessions. The current Analysis Database workflow includes:

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
- DataFrame Preview keeps source, row-limit, and visible timestamp information in a compact header so the table retains maximum usable space;
- Saved artifact actions sit above the artifact list, and Database Builder gives the database list and manifest/details area equal display space.

GUI code collects user selections and presents dialogs. It must not manually rewrite `manifest.json`, move/delete `analysis_databases/{database_id}/`, invent persistence rules, classify artifact recovery state locally, or replace Analysis Database components during build/rebuild. Recovery UI actions are intent surfaces only: status classification belongs to `ArtifactRecoveryPlanner`, artifact regeneration belongs to `ArtifactRecoveryRegenerator` / `ArtifactRecipeExecutor`, and linked database materialization belongs to `ArtifactRecoveryDatabaseRebuilder` / `AnalysisDatabaseStore`.

## Current Historical Chart / Study workflow — 2026-05-18

The historical chart stack is now hardened around the ownership chain:

```text
Core dataset truth → controller/session truth → panel chart-local study truth → workspace pane/layout contracts → pane handoff → renderer execution
```

Accepted behavior includes:

- dataset selection is Core/data-backed through `HistoricalDatasetService` catalog APIs and `CoreBridge`, not GUI folder-walking;
- dataset-open and resident-slice async results are marshalled back to the GUI thread and guarded against stale dataset/open-generation/request results;
- controller apply keeps full-dataset compute truth separate from resident-local render truth;
- renderable outputs are the only outputs that become chart series; accidental empty render payloads fail unless the tool explicitly allows empty render output;
- non-renderable but `analysis_usable` outputs remain valid temporary construct sources without entering the renderer;
- save writes full-dataset artifacts with explicit params, bindings, and durable saved-source lineage where available;
- active construct saved identity includes deterministic `__h<hash8>` identity;
- style changes invalidate static render caches through public workspace/pane/surface contracts instead of panel reach-through into renderer internals;
- `Series.values` consumers honor the `Sequence` contract;
- `HistoricalDatasetService` exposes explicit dataset-cache invalidation so OHLCV rewrites do not leave stale in-memory timelines/slices.

M6/M6B completed release-check/test reconciliation and full uploaded test validation without production-code changes.

## Current Historical Data Manager / Workspace layout workflow — 2026-05-19

Historical chart sessions hosted by `HistoricalDataManagerWindow` now support an 8-slot embedded workspace without changing chart-session, controller, renderer, data, or financial-tool ownership.

Accepted workspace behavior includes:

- up to 8 embedded historical chart panels;
- stable logical slot identity ordered as `1-2`, `3-4`, `5-6`, `7-8`;
- detached charts reserve their original slot and dock back into that same slot;
- chart-level Position controls can move a chart to another slot or swap with an occupied slot while protecting reserved detached slots;
- two visualization modes: `Scroll 4` for scrolling beyond the first four visible charts, and `Fit 8` for fitting all embedded charts into the usable workspace;
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
- Universal Trend Classifier historical mode consumes controller-injected Peaks & Troughs event columns for independent directional-trend and horizontal-range detection, preserves invalid-gap honesty, and keeps compute-only runtime ownership with renderer-only drawing;
- Core/GUI feed dependency removed from the Bybit feed boundary;
- historical dataset service exposes explicit public timeline/columns/dataframe APIs;
- historical chart controller, panel, workspace, panes, and renderers are physically split while preserving public import façades;
- workspace owns Autoscale/manual-y and pane contracts;
- viewport remains horizontal camera only;
- panes remain handoff boundaries;
- renderers remain execution-only.