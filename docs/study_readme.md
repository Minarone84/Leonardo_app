# STUDY INSTANCE SYSTEM (Chart Study Architecture)

## 1. PURPOSE

This document defines the architecture and behavior of **Chart Study Instances** within the Leonardo historical chart system.

The system provides a TradingView-like experience for managing indicators, oscillators, and constructs directly on the chart.

It enforces strict separation between:

- **Computation (what is calculated)**
- **Display (how it looks)**
- **Chart session state (what is currently shown)**
- **Layout (where it is rendered)**

---

## 2. CORE CONCEPT

### ChartStudyInstance

A **ChartStudyInstance** represents a single study applied to a chart session.

Examples:

- EMA 14 overlay
- SMA 50 overlay
- RSI 14 oscillator
- MACD (multi-series oscillator)

It is:

- Chart-session local
- Editable
- Removable
- Independent from persistence
- Pane-agnostic

---

## 3. RESPONSIBILITIES

A ChartStudyInstance encapsulates four domains:

### 3.1 Identity

- instance_id
- family (indicator / oscillator / construct)
- tool_key (ema, sma, rsi...)
- display_name
- dataset_id

NOTE:  
Studies do **not** own pane placement. Pane/layout is handled by the workspace.

---

### 3.2 Computation (Inputs)

Defines how values are calculated.

- params (e.g. period=14)
- source_kind (temporary | saved_artifact)
- artifact_path (optional)
- saved_artifact_name (optional)

---

### 3.3 Display (Style)

Defines how the study is rendered.

- color
- line_width
- line_style
- visible
- show_label
- show_value

Style is:

- chart-local
- not persisted
- independent from computation

---

### 3.4 Runtime State

Live state used during rendering.

- last_value
- render_keys (list of series identifiers)
- selected
- status (active | hidden | updating | error)
- error_text

---

## 4. MULTI-SERIES STUDY MODEL

A study may produce **one or more render series**.

Examples:

- RSI → 1 series
- MACD → multiple series (line, signal, histogram)
- future studies → bands, zones, envelopes

Rules:

- A single study instance owns **all its render series**
- All render series share the same `instance_id`
- Each render series has its own `render_key`
- The study runtime stores all associated render keys

---

## 5. RENDER KEYS (CRITICAL CONCEPT)

Each rendered series is assigned a unique **render_key**.

Render keys are the ONLY link between:

- chart-rendered series
- ChartStudyInstance
- UI interactions

They are used to:

- resolve study from chart interactions
- edit a study
- remove a study
- update style without recomputation

Rules:

- stored in `ChartStudyRuntimeState.render_keys`
- unique per study instance
- regenerated on study replacement
- never persisted across sessions

---

## 6. KEY ARCHITECTURAL PRINCIPLE

### Strict Separation of Responsibilities

| Responsibility | Owned By |
|------|--------|
| computation | Core / Study |
| series structure | Study |
| rendering | ChartWorkspaceWidget |
| pane layout | ChartWorkspaceWidget |
| lifecycle | HistoricalChartPanel |
| persistence | FinancialToolManager |

---

### Critical Rule

Studies:

- DO NOT know about panes
- DO NOT control layout
- DO NOT decide rendering location

They ONLY:

- define computation
- produce series

---

## 7. STUDY LIFECYCLE

### Apply

Triggered from FinancialToolManagerWindow.

Flow:

- controller computes series
- panel receives series_list
- workspace renders series
- study is registered

---

### Edit (Inputs)

Triggered from chart UI.

Uses **replace-on-apply model**:

- old study is removed
- new computation is executed
- new study instance replaces old one
- new render keys are generated

---

### Style Update

- affects only visual properties
- does NOT recompute data
- re-renders existing series
- preserves render keys

---

### Remove

- removes study from chart session
- removes associated render series
- does NOT delete saved artifacts

---

## 8. STUDY STATES

### Source States

- temporary
- saved-linked
- saved-loaded

### Runtime States

- active
- hidden
- updating
- error

---

## 9. CHART STUDY REGISTRY

Each chart session owns a **ChartStudyRegistry**.

Responsibilities:

- add study
- remove study
- lookup by instance_id
- resolve by render_key
- enumerate studies
- maintain order

Owned by:

- `HistoricalChartPanel`

---

## 10. UI MODEL

Each study appears as a chart-managed element.

Controls:

- Edit (computation)
- Style (visual)
- Remove

Future extensions:

- visibility toggle
- value display
- legend expansion

---

## 11. SETTINGS MODEL

### Inputs

- computation parameters

### Style

- visual settings

### Source (future)

- linkage to saved artifacts

---

## 12. ARCHITECTURAL PLACEMENT

### HistoricalChartPanel

- owns ChartStudyRegistry
- manages lifecycle
- resolves UI signals

### HistoricalChartController

- computes study data

### ChartWorkspaceWidget

- renders series
- manages panes
- manages layout

### FinancialToolManagerWindow

- defines studies
- edits computation inputs
- handles persistence intent

---

## 13. DESIGN RULES

1. Study instance is the unit of chart management
2. Studies are pane-agnostic
3. Display changes do not recreate studies
4. Computation changes use replace-on-apply
5. Removing a study does not delete stored data
6. Style is chart-local only
7. Render keys are the ONLY interaction bridge
8. Multi-series studies are first-class citizens
9. Layout is owned by the workspace, not the study

---

## 14. MINIMUM DATA STRUCTURE

```python
from dataclasses import dataclass, field


@dataclass
class StudyComputationConfig:
    family: str
    tool_key: str
    params: dict
    source_kind: str
    artifact_path: str | None = None


@dataclass
class StudyDisplayStyle:
    color: str = "#3B82F6"
    line_width: int = 2
    line_style: str = "solid"
    visible: bool = True
    show_label: bool = True
    show_value: bool = True


@dataclass
class ChartStudyRuntimeState:
    last_value: float | None = None
    render_keys: list[str] = field(default_factory=list)
    selected: bool = False
    status: str = "active"
    error_text: str | None = None


@dataclass
class ChartStudyInstance:
    instance_id: str
    dataset_id: str
    display_name: str
    computation: StudyComputationConfig
    style: StudyDisplayStyle
    runtime: ChartStudyRuntimeState

15. SUMMARY

The ChartStudyInstance system provides:

chart-local study lifecycle

multi-series study support

strict separation of computation, display, and layout

render-key based interaction mapping

replace-on-apply consistency model

This architecture enables:

scalable study management

clean integration with pane-based rendering

future support for complex studies (MACD, bands, constructs)

This is the foundation for all future chart study behavior.

If this file is not followed, the system will degrade into:    