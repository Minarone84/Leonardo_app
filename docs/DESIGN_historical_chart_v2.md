Leonardo  
DESIGN — Historical Chart v2

Version: v2.1  
Date: 2026-03-20  
Scope: Historical Data Visualization Workspace (Embedded + Floating, OHLC + Volume, detachable panels, financial tools, async-safe persistence, construct system)

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
- applying indicators, oscillators, and constructs to historical charts
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
- owns study registry
- forwards tool actions
- maintains dataset identity
- owns chart-local lifecycle of studies

---

### 3.5 HistoricalChartWindow

Floating shell for one panel.

---

### 3.6 HistoricalChartController

- loads data
- applies financial tools
- async-safe
- emits structured results

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
- apply / save intent

Does NOT:

- compute results
- manage chart layout
- manage pane logic

---

## 3.9 Study System (Chart-Local)

A **study** represents a chart-applied computation instance.

Studies are:

- chart-session scoped
- non-persistent (runtime)
- decoupled from tool persistence

---

### Study Responsibilities

- render series (if applicable)
- track runtime state
- support edit/remove/style
- integrate with workspace layout

---

## 3.10 ChartStudyRegistry

Per-panel registry:

Stores:

- `instance_id`
- `pane_target`
- computation config
- runtime render keys
- style

Acts as the single source of truth for chart-local studies.

---

## 3.11 Study Rendering Model (v2.1 Update)

### Key Principle

Rendering is **behavior-driven**, NOT family-driven.

Old model:
- indicator → overlay
- oscillator → lower pane

New model:
- rendering determined by **ToolBehaviorSpec**

---

### Flow

Tool → Controller → Panel → Workspace → Render

---

### Behavior-Driven Routing

Each study declares:

- `output_mode`
  - `overlay`
  - `oscillator-pane`
  - `non-visual`

Panel resolves:

- pane target
- render path
- lifecycle rules

---

## 3.12 Study Lifecycle

Apply:
- compute result
- register study
- render if applicable

Edit:
- replace-on-apply

Remove:
- remove from workspace
- remove from registry

Style:
- re-render only
- computation untouched

---

## 3.13 Study Types (v2.1 Extension)

### Indicators

- overlay-rendered
- price-pane attached

### Oscillators

- rendered in dedicated lower panes
- pane-managed

### Constructs (NEW)

Constructs are analysis-oriented tools.

They are NOT defined by rendering.

They may be:

#### 1. Overlay Constructs
- render on price pane
- behave like indicators (visually)

#### 2. Oscillator Constructs
- render in lower pane
- behave like oscillators (visually)

#### 3. Non-Visual Constructs
- produce no chart rendering
- exist only as analytical state

---

### Important Design Rule

Construct behavior is **explicitly declared**, not inferred.

---

## 3.14 Non-Visual Studies (NEW)

Non-visual studies:

- produce no `series_list`
- are still valid studies
- are stored in the registry
- participate in lifecycle (apply/remove)

They:

- do NOT render
- do NOT support styling
- do NOT create panes

---

## 3.15 Study Style System

Style is:

- local to chart
- non-persistent
- decoupled from computation

Constraints:

- only renderable studies support styling
- non-visual studies reject style operations

---

## 3.16 Financial Tool vs Study

Financial Tool:
- definition + parameters
- persistence layer concept

Study:
- runtime instance on chart
- ephemeral

---

## 3.17 Oscillator Pane Management (v2 Extension)

### Purpose

Oscillators and oscillator-like constructs use managed panes.

---

### Architecture

Three independent layers:

1. Computation
2. Display
3. Layout

---

### Managed Pane System

Workspace introduces:

- `_oscillator_panes_by_id`
- `_oscillator_states_by_id`
- `_oscillator_pane_order`
- `_study_to_pane_id`

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

### Pane Reordering

- move up/down
- deterministic layout
- size preservation

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

## 7. Summary (v2.1)

Historical Chart v2 now provides:

- multi-chart workspace
- detachable sessions
- async-safe loading
- financial tool workflow
- chart-local study system
- pane-managed oscillators
- behavior-driven rendering model
- construct system (overlay / oscillator / non-visual)
- support for analysis-only (non-visual) studies
- interactive lifecycle (apply/edit/remove/style)
- render-key mapping

The system is now a **flexible analytical charting environment**, cleanly separated from:

- trading execution
- backtesting
- strategy systems