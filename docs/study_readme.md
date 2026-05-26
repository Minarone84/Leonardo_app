# Leonardo Study System (Current State)

Version: v1.12
Date: 2026-05-26

## Purpose

This README documents the **chart-session-local study system** used by Leonardo historical charts.

It covers:

- what a study is
- where study ownership lives
- how studies are registered and updated
- how chart-local style is stored and reapplied
- how resident-slice refresh interacts with already-applied studies
- how pane targeting and renderability are enforced

This document does **not** define construct naming templates or saved construct file identity.
Those rules belong in the dedicated construct policy document.

---

## Overview

A **financial tool** is a reusable analytical definition that exists independently of any chart session.
A **study** is the chart-local runtime instance of that tool after it has been applied to a specific chart session.

The study layer exists so Leonardo can keep these concerns separate:

- computation truth
- chart-session identity
- user-facing semantic metadata
- chart-local styling
- pane placement
- resident-local render payloads
- runtime UI state

This separation is non-negotiable. It follows the project's no shared responsibilities rule: each layer may pass explicit state or parameters downstream, but it must not overtake another layer's job.

A study may be:

- a price-pane overlay
- an oscillator-pane study
- a non-visual chart-session object with no render payload

The chart must treat study state as **chart-local session state**, not as global application state and not as persistence identity.

---

## Core Principles

The study system must be:

- chart-local
- dataset-bound
- immutable by replacement rather than ad hoc mutation
- separated from computation truth
- separated from pane ownership
- separated from renderer behavior
- resident-local at render time
- style-only on visual edits

Important rule:

A study is part of the current chart session.
It is **not** the financial tool definition itself, and it is **not** the persisted artifact identity.

---


## Values Buffer Contract

Render payload values are treated as immutable buffers.

Rules:
- downstream code must use `len()` / indexed access instead of truthiness or list-only assumptions;

- `Series.values` must not be mutated in place. Updates must replace the `values` object reference.
- `Series.values` may be a `list[float]` or any `Sequence[float]` supporting `__len__` and `__getitem__`.
- Downstream consumers (autoscale, painters, y-range caches) must not assume list-only operations.

This supports cache correctness and prevents pan/zoom and crosshair paths from paying repeated allocation costs.

## Separation of Responsibilities

### Controller

`HistoricalChartController` owns:

- canonical dataset/session truth
- canonical full-dataset study truth
- resident slice truth
- resident-local study projection
- timeline-first projection alignment for runtime output before any legacy no-timeline positional fallback
- non-renderable analysis-source retention for temporary construct chaining
- apply-time renderable filtering
- apply vs save boundary behavior

The controller may compute on the full dataset, but it must emit **resident-local render payloads only**.

### HistoricalChartPanel

`HistoricalChartPanel` owns:

- chart-session study lifecycle
- `ChartStudyRegistry`
- chart-local study identity for the open chart
- translation from controller projections back onto chart-local study ids
- chart-local render-key namespacing for duplicate same-config studies
- chart-local style persistence
- style-only reapply behavior
- final chart-local styled projected-payload resolution before workspace reapply
- default-style seeding into study state
- default style-module seeding where applicable
- oscillator visual-policy seeding
- study edit/remove wiring for the current session

The panel does **not** own computation truth, persistence semantics, pane layout, or renderer behavior.

### Workspace

`ChartWorkspaceWidget` owns:

- pane registry
- pane ordering
- study-to-pane mapping
- managed overlay grouping
- pane-local visual policy state
- batched projected-study reapply and pruning of managed pane/render state
- faithful application of final resident-local study payloads into chart panes

Workspace owns pane behavior.
Studies do not own layout.

### Renderer

Renderers consume:

- resident-local series
- chart-local style state
- pane-local visual policy

Renderers must not:

- compute studies
- define semantic defaults
- decide pane placement
- reinterpret full-dataset indexing
- become study registries

---

## Study Families

The study system currently supports three families:

- `indicator`
- `oscillator`
- `construct`

### Indicators

Indicators are price-pane studies.

Rules:

- pane target must be `price`
- runtime outputs may be one or many renderable lines or sparse renderable event signals
- chart-local styling remains downstream of computation

Validated current indicator-family note:

- single-signal price overlays currently include SMA, EMA, TEMA, HMA, and KAMA
- multi-signal price overlays currently include BB and HCK
- event-style price overlays currently include `peaks_troughs`
- `peaks_troughs` emits sparse confirmed fractal event signals for 3, 5, 7, 9, and 11-bar peak/trough windows
- `peaks_troughs` uses chart-local marker-style rendering on the price pane rather than connected line semantics
- `universal_trend_classifier` is a price-pane market-structure study whose finalized historical directional trend path consumes saved/injected `peaks_troughs` event columns
- UTC may consume separate saved/injected Peaks & Troughs streams for directional trend classification and horizontal range discovery (`trend_fractal_window` and `range_fractal_window`)
- UTC horizontal ranges use range fractals to discover/define a range zone; once active, range continuation is governed by price acceptance, break mode, and pending breakout/reclaim state rather than by requiring more fractals
- UTC emits non-renderable boolean state outputs such as `uptrend`, `downtrend`, and `horizontal_range`; those state outputs may drive segmented background/fill behavior but must not become normal connected chart lines
- UTC renderable horizontal-range outputs remain `hor_upper`, `hor_lower`, and sparse range start/end markers; controller projection still filters renderable chart series from full-dataset truth into resident-local payloads
- UTC directional semantics allow the shared-extreme rule: an uptrend may end at the same peak where a downtrend starts, and a downtrend may end at the same trough where an uptrend starts; multi-bar opposite-trend overlap is invalid
- UTC invalid OHLC/source rows are hard continuity breaks; historical directional trend intervals must not bridge NaN or malformed candle/source gaps
- HCK also emits a non-renderable utility/state output (`vwap_color`) which must not be injected into the chart renderer

### Oscillators

Oscillators are oscillator-pane studies.

Rules:

- pane target must be `oscillator`;
- visualization is governed by pane-local visual policy;
- oscillator studies do not own pane layout directly;
- runtime may emit one or many renderable oscillator series;
- chart-local style defaults must resolve dynamic parameterized signal names before persistence into study state.

Current oscillator-family rendering baseline:

- single-line bounded: RSI and MFI;
- two-line bounded: ARSI main line plus ARSI signal/mean line;
- multi-line bounded: TDI RSI;
- multi-line signal: SMI;
- unbounded: OBV;
- histogram + line: Volume and `volume_mean_{period}`.

Current dynamic oscillator style resolution includes:

- `rsi_*`, `arsi_*`, `arsi_signal_*`, `mfi_*`;
- `smi_*` and `smi_signal_*`;
- `tdirsi_fast_ma_*`, `tdirsi_slow_ma_*`, `tdirsi_up_*`, `tdirsi_dn_*`, `tdirsi_mid_*`;
- `volume_mean_*`.

Threshold-aware oscillator coloring is visual-only. It splits line segments at the actual threshold crossing and uses the persisted/user-selected series color in the neutral region. Overbought/oversold colors come from pane visual policy.

### Constructs

Constructs may be:

- non-visual
- price-pane studies
- oscillator-pane studies

Construct behavior depends on runtime output structure and resolved renderability metadata.

Construct naming and saved-identity rules are documented separately.

---

## Study Data Model

The study system uses immutable dataclasses to keep chart-local state explicit.

### `StudyComputationConfig`

This stores the chart-session computation identity for one study instance.

Fields include:

- `family`
- `tool_key`
- `params`
- `source_kind`
- `artifact_path`
- `saved_artifact_name`

Supported source kinds currently include:

- `temporary`
- `saved-linked`
- `saved-loaded`

Important rule:

This is chart-session computation metadata.
It is not renderer state.

### `StudyUserMetadata`

This stores user-facing semantic metadata for one chart-local study instance.

Fields include:

- `important`
- `description`
- `dataset_role`

Applied historical chart studies expose a visible `Metadata...` action in price overlay rows and oscillator pane headers. The action opens the Study Metadata dialog and updates `StudyUserMetadata` through the chart-local study registry path.

Important rules:

- metadata is semantic context only;
- metadata does not affect computation, rendering, style, runtime state, artifact identity, or recipe identity;
- `dataset_role` is a hint for reporting and user review, not proof of tool identity or Analysis Database geography;
- `important` may be used by Study Environment recipe export filtering, but it does not change computation or rendering;
- old serialized study payloads load with default metadata values;
- study serialization/deserialization, Study Environments, and Workspace Snapshots preserve `user_metadata`;
- computation edit/reapply must preserve existing metadata unless the user explicitly edits it;
- updating an existing Study Environment stores the current live study metadata into the selected saved environment.

Study metadata can be edited from the live chart through `Metadata...` or from saved Study Environments through the Study Environment Manager. The manager edits only serialized `user_metadata`; it does not edit computation params, style, bindings, or recipe definitions.

### `StudyDisplayStyle`

This stores chart-local display state.

It includes:

- legacy/global compatibility fields
- `signal_styles`
- `fill_styles`
- `style_modules`

Important rule:

The legacy/global fields are compatibility-only.
They are not the identity of expanded renderer-facing segmented payload. Historical segmented visual derivation may expand one logical study into several renderer-facing series/fills while chart-local signal/fill style truth remains anchored to the logical signal names and fill ids.
They are **not** the source of truth for static defaults.

### `StudySignalStyle`

Per-signal chart-local style for one emitted render line or event marker payload.

Examples:

- BB middle / upper / lower
- HCK fast / slow VWAP
- TDI multi-line oscillator outputs
- Peaks & Troughs peak/trough fractal markers

Important note:

Per-signal style now also covers marker-oriented visual fields used by event-style studies, such as:

- render mode
- marker shape
- marker text
- marker text color
- marker size
- marker offset

### `StudyFillStyle`

Static chart-local fill configuration between two study-owned signals.

Examples:

- BB band fill
- HCK fast/slow fill

### `StudyStyleModuleState`

Declarative chart-local style-module state.

Examples:

- `conditional_line_color`
- `conditional_fill_color`
- future module-driven styling behavior

Style modules are runtime visual logic only.
They do not change computation truth.

### `ChartStudyRuntimeState`

This stores runtime-facing chart-session state such as:

- `last_value`
- `selected`
- `status`
- `error_text`
- `render_keys`

Supported runtime status values currently include:

- `active`
- `hidden`
- `updating`
- `error`

Important rule:

Runtime `render_keys` are renderer-facing **chart-local identifiers** for the current chart session.
They may be namespaced per study instance and must not be treated as controller computation identity.
For historical segmented studies, runtime `render_keys` may legitimately be resynced after style resolution so the registry tracks the final explicit renderer-facing payload while logical signal identity remains in `signal_styles` / `fill_styles`.

Important UI rule:

UI actions (style/edit/remove) must be routed by chart-local `ChartStudyInstance.instance_id`, not by `render_keys`. Render keys are renderer-facing identifiers and may be resynced after style resolution.

### `ChartStudyInstance`

This is the full chart-session study object.

It includes:

- `instance_id`
- `dataset_id`
- `pane_target`
- `display_name`
- `computation`
- `style`
- `user_metadata`
- `runtime`

Important pane-target rules:

- indicator studies must target `price`
- oscillator studies must target `oscillator`
- construct studies may target `None`, `price`, or `oscillator`

A study is considered renderable only when it has non-empty runtime `render_keys`.

### Controller projection identity vs chart-local study identity

These are different identities and must remain different.

- controller projection identity identifies shared computation truth and the current resident-local projection
- chart-local study identity identifies one panel-owned study instance
- multiple chart-local study instances may legitimately share one controller projection when the same study config is applied more than once
- duplicate chart-local studies must therefore keep separate `instance_id`, style state, runtime state, and renderer-facing render keys

Important rule:

Duplicate same-config studies may share controller compute truth, but they must not collapse into one chart-local study instance downstream.

---

## ChartStudyRegistry

`ChartStudyRegistry` is the chart-session-local registry of displayed studies.

It is intentionally:

- GUI-agnostic
- persistence-agnostic
- pane-layout-agnostic
- computation-agnostic

It owns:

- study membership in the current chart session
- study ordering
- lookup by `instance_id`
- chart-local updates by replacement

It supports operations such as:

- `add`
- `remove`
- `get`
- `list_all`
- `list_for_pane`
- `update_style`
- `update_signal_style`
- `update_fill_style`
- `upsert_style_module`
- `update_inputs`
- `update_runtime`
- `select_only`

Important rule:

The registry stores study state.
It does **not** compute studies, apply panes, or own renderer payloads.

---

## Apply-Time Lifecycle

The study lifecycle begins when a financial tool is applied to a chart.

### Apply flow

`controller → panel → registry → workspace → renderer`

At apply time:

1. the controller computes using full-dataset truth when required
2. the controller filters non-renderable outputs
3. the controller trims emitted render payloads to the current resident slice
4. the panel creates or updates the chart-session study instance
5. the panel maps controller projection identity onto chart-local study identity when needed
6. the panel persists resolved default style into study state
7. the panel seeds any default style modules or oscillator visual policy
8. the panel resolves chart-local render identity and final resident-local styled payloads, including explicit segmented renderer-facing payload where historical conditional rendering requires it
9. the panel resyncs renderer-facing render keys where the final styled payload differs from the logical base payload
10. the workspace applies that resident-local payload to the correct pane path as one coherent pane update
11. the renderer draws the resulting resident-local payload

Important rule:

A study may store full chart-local display state, but the renderer still receives only resident-local values.

---

## Resident Refresh and Reprojection

Historical study behavior must stay stable during pan and zoom.

The controller therefore retains:

- canonical full-dataset study truth
- current resident-local study projections

When the resident slice changes:

- the controller rebuilds resident-local projected series from stored study truth using explicit `ts_ms` / `time` / non-positional index alignment where available
- the panel maps controller-projected payloads back onto chart-local study ids
- the panel resolves the final chart-local styled series/fill payload once per chart-local study instance
- the workspace reapplies those final resident-local payloads as one coherent batch while preserving pane ownership
- the viewport remains camera state only
- the render layer consumes the refreshed resident-local payload

### Duplicate same-config studies

Historical refresh must preserve duplicate chart-local studies correctly.

That means:

- one controller projection may fan out to multiple chart-local study instances
- the panel must not collapse projected refresh to a single first-match study when multiple chart-local instances legitimately share the same controller compute truth
- workspace must receive chart-local study ids and chart-local render keys so duplicate same-config studies do not collide in managed pane/render state

Important rule:

Panning around a historical chart must behave like moving a camera over existing chart-session truth.
It must not turn the renderer into a computation owner.

### Style and refresh rule

Resident refresh may rebuild resident-local projected payloads.
Style edits must **not** trigger study recomputation.
Style reapply may invalidate renderer static-scene caches only through public workspace/pane/surface contracts, never by mutating renderer private cache fields.
When a study uses historical segmented visual derivation, the panel must re-resolve from controller-projected base series rather than from already segmented workspace/model series so workspace/model do not become a second semantic owner.

### Performance rule

Resident reapply should occur as one coherent study-application refresh, not as a chain of unrelated mini-passes that cause visible redraw churn.

---

## Renderability Rules

Renderability is resolved upstream through tool metadata and controller filtering.

This means:

- only outputs explicitly resolved as `renderable=True` may become controller-owned chart-study lines and downstream chart render series
- non-renderable `analysis_usable=True` outputs may be retained by the controller as temporary source truth, but they must not create render keys
- empty render payloads for chart-renderable tools must be rejected unless the tool explicitly allows them
- `renderable=False` outputs remain valid runtime outputs, but must not be injected into the chart renderer
- there must be no fallback from “no renderable outputs” to “render everything that exists”

Important rule:

The study layer must not “helpfully” render extra runtime lines just because they exist.

That decision belongs upstream at the controller boundary. Saved artifacts may still persist non-renderable outputs when valid; saved-source selection is driven by artifact sidecar metadata rather than chart-study renderability alone.

---

## Style System

Study styling is chart-local and visual-only.

### Default source of truth

Static defaults come from:

`study_style_defaults.py`

These defaults must be resolved at apply time and persisted into `ChartStudyInstance.style`.

This includes static marker defaults for event-style studies such as `peaks_troughs`, including default marker render mode, shape, text, size, visibility, and baseline offset.

### Style layers

The current style stack includes:

- persisted default style state
- per-signal style overrides
- per-fill style overrides
- style modules
- grouped chart-local style controls that fan out into per-signal overrides when a study exposes a semantic group edit surface

Validated grouped-control example:

- `peaks_troughs` exposes chart-local grouped `Above` and `Below` controls
- `Above` updates all peak fractal marker offsets together
- `Below` updates all trough fractal marker offsets together
- this remains style-only and is persisted back into per-signal chart-local style truth

### Critical rule

If a renderer appears to have meaningful defaults that are not already present in chart-local study state, the upstream contract is broken.

### Compatibility rule

The legacy/global study-style fields still exist for compatibility, but they must not overwrite resolved chart-local defaults with neutral placeholder values.

---

## Default Style Persistence

The panel is responsible for seeding and persisting default chart-local style state.

Why this matters:

- study defaults must survive slice refresh
- style reapply must not depend on renderer fallback
- later style edits must start from explicit chart-local truth

The panel may inspect the currently applied workspace/model series to persist already-resolved defaults when necessary, but that does not change ownership:

- workspace still owns applied chart payloads
- panel still owns study lifecycle and chart-local style truth

---

## Style Modules

Style modules are declarative chart-local visual behavior.

They are:

- study-owned
- runtime-configured
- renderer-consumed
- computation-independent

Current examples include:

- conditional line coloring
- conditional fill coloring

### HCK support

The panel currently seeds default HCK module state for:

- `conditional_line_color`
- `conditional_fill_color`

Validated HCK rule:

- these modules represent **historical segmented** chart-local visual behavior, not whole-study latest-state tinting
- panel/style-resolver logic expands the logical HCK study into explicit bullish/bearish renderer-facing series and fills
- crossover continuity is solved upstream during payload construction
- the renderer consumes that explicit segmented payload only

That keeps HCK conditional coloring part of chart-local study state instead of renderer-specific hardcoding.

---

## Oscillator Visual Policy

Oscillator visual policy is separate from study style.

This policy defines how oscillator data is interpreted in a pane.

Examples:

- fixed bounds
- auto-fit behavior
- guide levels
- threshold-aware line coloring
- pane-local vertical interaction
- pane-level fills and levels

Ownership flow:

`panel → workspace → pane → renderer`

Important rule:

Oscillator visual policy is:

- chart-local
- pane-scoped
- visual-only
- not part of computation
- not part of persistence identity

Current bounded oscillator policy notes:

- RSI and MFI use the generic `70 / 50 / 30` guide model.
- ARSI uses the Ultimate RSI-style `80 / 50 / 20` guide model.
- Threshold-aware line coloring applies outside the configured upper/lower bounds and must not overwrite neutral user style.
- Volume uses an unbounded auto-range pane; `volume` is histogram-rendered and `volume_mean_{period}` is a normal line series.

---

## Editing, Removal, and Reapply

### Editing computation

When study inputs or computation parameters change:

- the study computation config changes
- the controller owns recomputation
- the resulting chart-visible study may replace the previous render payload

### Editing style

When style changes:

- the study remains the same study instance
- computation truth stays untouched
- the panel updates chart-local style state
- the panel resolves the final chart-local visual payload from already-rendered/projected data
- the workspace reapplies that payload once with new visual state only

### Removal

When a study is removed:

- the panel removes the study from the registry
- the workspace removes the rendered payload from the correct pane path
- other studies must remain untouched

### Dock / undock behavior

Floating and re-docking a chart must preserve chart-session study state.

The shell may change, but the chart session must not lose its studies.

---

## Runtime Selection and Visibility

The registry/runtime model supports chart-session interaction state such as:

- selected study
- active vs hidden vs updating vs error status
- last value display metadata
- render-key tracking for applied payloads

This state belongs to the chart session and must not be rebuilt from renderer inspection.

---

## What This README Does Not Define

This file does **not** define:

- construct output naming templates
- saved construct file identity
- full financial-tool spec semantics
- pane layout rules in detail
- renderer drawing algorithms
- controller slice policy details

Those belong in their dedicated documents.

In particular:

- construct naming and runtime output policy belong in `construct_readme.md`
- broader financial-tool architecture belongs in `DESIGN_financial_tools.md`
- historical chart-space and resident-slice behavior belong in `DESIGN_historical_chart_v2.md`

Notebook POI and Potential Trade markers are also outside the study system. They are runtime chart annotations derived from Notebook rows. They do not enter `ChartStudyRegistry`, do not create `ChartStudyInstance` objects, do not become financial-tool outputs, and are not saved as Study Environment content.

Study Environment recipe export is a Data Manager workflow built from serialized study payloads. It may use `important` for filtering and carry `description` / `dataset_role` as report context, but it must not treat metadata as computation truth, style truth, artifact identity, recipe identity, or geography proof. Export planning and persistence are owned by data-layer services, not by the chart study registry. Saving a Study Environment does not directly persist recipes; recipe creation happens only through the Data Manager export workflow.

---

## Non-Negotiable Rules

The study system enforces:

- studies are chart-session-local
- studies are tied to one dataset identity
- studies do not own pane layout
- style changes do not trigger recomputation
- resident refresh does not move computation into renderers
- style/cache invalidation does not move renderer cache ownership into the panel
- only renderable outputs become chart series
- study metadata remains semantic/user-facing only
- controller projection identity must remain separate from chart-local study identity
- duplicate same-config studies may share controller compute truth but not chart-local identity
- render keys are chart-local identifiers, not computation identity
- default style truth must be persisted into study state
- oscillator policy must remain separate from style
- workspace owns pane/layout behavior
- panel owns study lifecycle and projected-refresh mapping back onto chart-local studies
- controller owns full-study truth and resident-local projection
- renderers are execution-only surfaces
- notebook POI/PT markers are runtime annotations, not studies

---

## Final State

The current Leonardo study system is:

- chart-local
- registry-driven
- immutable by replacement
- resident-local at render time
- defaults-driven for style
- policy-aware for oscillators
- compatible with multi-signal and multi-output studies
- able to track expanded renderer-facing payload for historical segmented studies while preserving logical chart-local study identity
- separated cleanly from computation and persistence

This is the correct contract for studies in Leonardo.

Studies live **on** the chart session.
They do not own the chart engine, and they do not redefine chart truth.

---

## Validation Basis

This README is aligned with the validated current implementation across:

- `gui/chart/studies.py`
- `gui/windows/historical_chart_panel.py`
- `gui/historical_chart_controller.py`
- `gui/chart/workspace.py`
- `gui_readme.md`
- `DESIGN_historical_chart_v2.md`
- `DESIGN_financial_tools.md`
- `construct_readme.md`

It reflects the current study-system contract:

`full-dataset compute truth → controller resident projection → panel chart-local identity/style resolution → workspace pane application → renderer execution`

No construct-only naming policy, deprecated study ownership model, or renderer-owned style truth should remain in this file. Notebook-owned POI/PT annotation truth should likewise remain outside the study system.
---

## Refactored Study/Panel Implementation — 2026-04-20
The study system remains chart-session-local. The refactor split `HistoricalChartPanel` into a façade plus panel-owned helper modules.

```text
gui/windows/historical_chart_panel.py
gui/windows/_historical_chart_panel/
    historical_chart_panel_study_apply.py
    historical_chart_panel_style.py
    historical_chart_panel_oscillator_policy.py
    historical_chart_panel_projection_bridge.py
    historical_chart_panel_messages.py
    study_style_dialog.py
```

### Responsibilities by helper

- `historical_chart_panel_study_apply.py` — apply payload validation, study registration, edited-study reuse, workspace handoff, remove/edit/move handlers.
- `historical_chart_panel_style.py` — chart-local render-key namespacing, default-style persistence, fill descriptors, HCK style-module seeding, final styled reapply.
- `historical_chart_panel_oscillator_policy.py` — oscillator bounds, guide levels, threshold-color policy, fills.
- `historical_chart_panel_projection_bridge.py` — controller projection to chart-local study fanout, duplicate same-config mapping, workspace projected payload construction.
- `historical_chart_panel_messages.py` — save success/error message construction.
- `study_style_dialog.py` — chart-local style editor.

### Fixed rules after refactor

- `historical_chart_panel.py` remains the public façade and chart-session owner.
- The private helper package is panel-owned only.
- Style edits remain visual-only and must not trigger recomputation.
- Duplicate same-config studies may share controller projection truth, but must keep separate chart-local `instance_id`, style state, and render keys.
- The style dialog is chart-local study UI, not general window/runtime logic.
