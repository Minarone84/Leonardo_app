# STUDY INSTANCE SYSTEM (Chart Study Architecture)

## 1. PURPOSE

This document defines the architecture and behavior of **Chart Study Instances** within the Leonardo historical chart system.

The goal is to introduce a TradingView-like system for managing indicators, oscillators, and constructs directly on the chart, without interfering with the Financial Tool Manager responsibilities.

This system separates:

* **Computation (what is calculated)**
* **Display (how it looks)**
* **Chart session state (what is currently shown)**

---

## 2. CORE CONCEPT

### ChartStudyInstance

A **ChartStudyInstance** represents a single study displayed on a chart.

Examples:

* EMA 14 on price chart
* SMA 50 overlay
* RSI 14 in oscillator pane

It is:

* Chart-session local
* Editable
* Removable
* Independent from persistence

---

## 3. RESPONSIBILITIES

A ChartStudyInstance encapsulates four domains:

### 3.1 Identity

* instance_id
* family (indicator / oscillator / construct)
* tool_key (ema, sma, rsi...)
* display_name ("EMA 14")
* dataset_id
* pane_target (price / oscillator)

### 3.2 Computation (Inputs)

Defines how values are calculated.

* params (e.g. period=14)
* source_kind (temporary | saved_artifact)
* artifact_path (optional)
* saved_artifact_name (optional)

### 3.3 Display (Style)

Defines how the study is rendered.

* color
* line_width
* line_style
* visible
* show_label
* show_value

### 3.4 Runtime State

Live state used during rendering.

* last_value
* selected
* status (active | hidden | updating | error)
* error_text

---

## 4. SUPPORTING OBJECTS

### StudyComputationConfig

Defines computation parameters.

### StudyDisplayStyle

Defines visual appearance.

### ChartStudyRuntimeState

Defines live runtime state.

### ChartStudyInstance

Combines all of the above.

---

## 5. KEY ARCHITECTURAL PRINCIPLE

Display and computation MUST remain separate.

Changing:

* color
* width
* visibility

must NOT trigger recomputation.

Changing:

* period
* source

must trigger recomputation but preserve the same instance.

---

## 6. STUDY LIFECYCLE

### Create

A study is created when applied from the Financial Tool Manager or from chart actions.

### Attach

The study is registered into the chart session.

### Render

The study is rendered by the ChartWorkspaceWidget.

### Update Style

Visual properties change without recomputation.

### Update Inputs

Triggers recomputation via controller.

### Remove

Removes study from chart session ONLY.
Does NOT delete saved artifacts.

---

## 7. STUDY STATES

### Source States

* temporary
* saved-linked
* saved-loaded

### Runtime States

* active
* hidden
* updating
* error

---

## 8. CHART STUDY REGISTRY

Each chart session owns a **ChartStudyRegistry**.

Responsibilities:

* add study
* remove study
* update style
* update inputs
* enumerate studies
* maintain order

Owned by:

* HistoricalChartPanel

---

## 9. UI MODEL (TRADINGVIEW STYLE)

Each study appears in the chart as a legend item:

Example:
EMA 14 104,235.7 [gear] [eye] [x]

Features:

* color swatch
* label
* live value
* settings button
* visibility toggle
* remove button

---

## 10. SETTINGS MODEL

Study settings dialog is split into:

### Inputs

* computation parameters

### Style

* visual settings

### Source (future)

* link to saved artifacts

---

## 11. ARCHITECTURAL PLACEMENT

### HistoricalChartPanel

* owns ChartStudyRegistry
* manages study lifecycle

### HistoricalChartController

* computes study data

### ChartWorkspaceWidget

* renders studies

### FinancialToolManagerWindow

* creates study definitions

---

## 12. DESIGN RULES

1. Study instance is the unit of chart management
2. Display changes do not recreate studies
3. Computation changes preserve instance identity
4. Removing a study does not delete stored data
5. Chart style is local, not persisted globally
6. Chart panel owns study instances

---

## 13. MINIMUM DATA STRUCTURE

```python
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
    selected: bool = False
    status: str = "active"
    error_text: str | None = None

@dataclass
class ChartStudyInstance:
    instance_id: str
    dataset_id: str
    pane_target: str
    display_name: str
    computation: StudyComputationConfig
    style: StudyDisplayStyle
    runtime: ChartStudyRuntimeState
```

---

## 14. SUMMARY

The ChartStudyInstance system introduces a robust, scalable, and user-friendly way to manage indicators, oscillators, and constructs directly on the chart.

It ensures:

* clean separation of responsibilities
* TradingView-like usability
* future extensibility

This is the foundation for all future on-chart study management features.
