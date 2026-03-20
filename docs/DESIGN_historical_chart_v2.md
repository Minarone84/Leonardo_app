Leonardo  
DESIGN — Historical Chart v2

Version: v2  
Date: 2026-03-19  
Scope: Historical Data Visualization Workspace (Embedded + Floating, OHLC + Volume, detachable panels, financial tools, async-safe persistence)

Reference:

DESIGN_historical_chart_v2

---

## 1. Purpose

Historical Chart v2 evolves the historical visualization system from a single top-level chart window model into a managed historical workspace.

The system is designed to allow:

- loading historical datasets from local canonical storage
- displaying up to 4 historical chart sessions inside `HistoricalDataManagerWindow`
- detachable chart panels that can float as top-level windows
- docking floating chart windows back into the historical workspace
- preservation of chart session state while changing shell/container
- async-safe Core/GUI separation
- applying indicators and oscillators to historical charts
- saving configured financial tools for later reuse and analysis

The historical chart remains primarily a visualization and research interface.

It is **not** yet:

- a strategy engine
- a backtesting runtime
- a trade execution interface

---

## 2. Architectural Principles

### 2.1 Separation of Concerns

Four distinct layers:

- Historical Chart Session → `HistoricalChartPanel`
- Workspace Management → `HistoricalWorkspaceWidget`
- Floating Shell → `HistoricalChartWindow`
- Financial Tool Management → `FinancialToolManagerWindow`

Design rule:

Chart content must be reusable independently of the shell window.

---

### 2.2 Async Discipline

- Core handles IO
- GUI uses `CoreBridge.submit()`
- No direct awaits in GUI
- UI updates only on Qt thread

---

### 2.3 Shell-Agnostic Chart Sessions

A chart session can move between:

- embedded workspace
- floating window

without recreation.

---

### 2.4 Dataset Identity First

All state and persistence is keyed by:

- exchange
- market type
- symbol
- timeframe

---

## 3. Implemented Components

### 3.1 HistoricalDataManagerWindow

- Hosts workspace
- Creates charts
- Max 4 panels

---

### 3.2 HistoricalChartSelectionDialog

Dataset selection flow:

Exchange → Market → Asset → Timeframe

---

### 3.3 HistoricalWorkspaceWidget

- Manages embedded charts
- Handles layout
- Handles detach/dock

---

### 3.4 HistoricalChartPanel

Core chart session:

- owns workspace
- owns controller
- forwards tool actions
- maintains dataset identity

---

### 3.5 HistoricalChartWindow

Floating shell for one panel.

---

### 3.6 HistoricalChartController

- loads data
- applies studies
- async-safe
- emits results

---

### 3.7 ChartWorkspaceWidget

Shared chart surface:

- model
- viewport
- panes
- rendering

---

### 3.8 FinancialToolManagerWindow

Handles:

- tool selection
- parameter config
- save/apply intent

Does NOT compute or persist directly.

---

### 3.9 Study System (Chart-Local)

Studies represent chart-applied computations.

Responsibilities:

- render series
- track active studies
- support edit/remove/style

---

### 3.10 ChartStudyRegistry

Per-panel registry:

- instance_id
- render_keys
- config
- style

---

### 3.11 Study Rendering Model

Flow:

Tool → Controller → Panel → Workspace → Render

Render keys link data ↔ UI.

---

### 3.12 Study Lifecycle

- Apply → compute + register
- Edit → replace-on-apply
- Remove → delete from workspace
- Style → re-render only

---

### 3.13 Study Style System

Style is:

- local
- non-persistent
- decoupled from computation

---

### 3.14 Chart UI Integration

Price pane supports:

- Edit
- Style
- Remove

Signals use `render_key`.

---

### 3.15 Financial Tool vs Study

Financial Tool = intent + persistence  
Study = runtime visualization

---

### 3.16 Current Limitations

- no cross-chart sync
- no dependency graph
- no replay system

---

## 3.17 Oscillator Pane Management (v2 Extension)

### Purpose

Oscillators are now pane-managed, not simple series attachments.

---

### Architectural Model

Three independent layers:

1. Computation (Core / Controller)
2. Display (Renderer / Style)
3. Layout (Workspace)

---

### Managed Pane System

Workspace introduces:

- `_oscillator_panes_by_id`
- `_oscillator_states_by_id`
- `_oscillator_pane_order`
- `_study_to_pane_id`

---

### OscillatorPaneState

Stores:

- pane_id
- study_instance_id
- title
- render_keys
- preferred_height

---

### Study → Pane Mapping

Current rule:

- 1 study = 1 pane
- multi-series per study supported

---

### Pane Lifecycle

Apply:
- create/update pane

Remove:
- destroy pane + series

Edit:
- replace-on-apply

Style:
- visual only

---

### Layout Management

- panes in vertical splitter
- height persistence
- deterministic ordering

Key functions:

- `_capture_managed_pane_heights`
- `_apply_default_sizes(force=True)`

---

### Pane Reordering

- move up/down
- rebuild layout
- preserve sizes

---

### Legacy Compatibility

Legacy `_oscillators` map still exists.

- series-based
- deprecated path

---

### Chart UI Integration

Pane-level actions:

- Edit
- Style
- Remove
- Move Up / Down

Signals use `study_instance_id`.

---

### Current Limitations

- no pane merging
- no pane splitting
- no per-series legend
- no layout persistence across sessions

---

## 4. Windowing Model

Embedded → Floating → Dock Back  
Panel is moved, not recreated.

---

## 5. Layout Policy

1 → full  
2 → split  
3 → 2x2  
4 → 2x2 full

---

## 6. Dataset Service

Handled by `HistoricalDatasetService`.

Canonical path:

data/historical/
{exchange}/
{market_type}/
{symbol}/
{timeframe}/
ohlcv/
candles.csv

---

## 7. Summary

Historical Chart v2 now provides:

- multi-chart workspace
- detachable sessions
- async-safe loading
- financial tool workflow
- chart-local studies
- pane-managed oscillators
- interactive lifecycle (apply/edit/remove/style)
- render-key mapping

The system is now a structured charting environment, still cleanly separated from:

- trading execution
- backtesting
- strategy systems