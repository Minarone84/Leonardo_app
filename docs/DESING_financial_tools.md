Leonardo  
DESIGN — Financial Tools System

Version: v1.0  
Date: 2026-03-20  
Scope: Indicators, Oscillators, Constructs, Tool Specs, Controller Integration, Chart Application

---

## 1. Purpose

The Financial Tools system defines how analytical tools are:

- defined (spec layer)
- computed (family modules)
- applied to charts (controller → panel → workspace)
- optionally persisted (future extension)

The system supports three tool families:

- Indicators
- Oscillators
- Constructs

These families share a unified specification model but differ in computation and runtime behavior.

---

## 2. Core Concepts

### 2.1 Financial Tool

A **financial tool** is a reusable analytical definition composed of:

- input requirements (market data)
- parameters
- computation logic
- output structure
- behavior metadata

It exists independently of any chart.

---

### 2.2 Study (Runtime Instance)

A **study** is a chart-local instance of a financial tool.

Properties:

- tied to a specific dataset
- stored in `ChartStudyRegistry`
- may or may not render on chart
- not persisted

---

### 2.3 Separation of Responsibilities

| Layer | Responsibility |
|------|--------|
| Spec | Defines tool metadata |
| Family Module | Performs computation |
| Controller | Executes tool and builds payload |
| Panel | Applies lifecycle and rendering |
| Workspace | Handles visual layout |

---

## 3. Tool Families

### 3.1 Indicators

- Render on price pane (overlay)
- Always chart-renderable
- Examples: SMA, EMA, Bollinger Bands

---

### 3.2 Oscillators

- Render in dedicated lower panes
- Pane-managed
- Examples: RSI, MFI, OBV

---

### 3.3 Constructs (NEW)

Constructs are **analysis-oriented tools**.

They are not defined by rendering behavior.

They support three modes:

#### Overlay Constructs
- Render on price pane
- Visually similar to indicators

#### Oscillator Constructs
- Render in lower panes
- Visually similar to oscillators

#### Non-Visual Constructs
- No chart rendering
- Used for analytical state, signals, metadata

---

## 4. Tool Specification System (`specs.py`)

### 4.1 ToolSpec

Defines a tool:

- key
- title
- kind (indicator / oscillator / construct)
- data inputs
- parameters
- output names
- behavior
- output metadata

---

### 4.2 ToolBehaviorSpec

Defines runtime behavior:

- `output_mode`
  - overlay
  - oscillator-pane
  - non-visual

- `chart_renderable`
- `supports_style`
- `supports_pane_layout`
- `supports_last_value`

This determines how the panel handles the tool.

---

### 4.3 ToolOutputSpec

Defines output expectations:

- structure (line-series, multi-line, analysis-only, etc.)
- output_names
- accepts_empty_render_output

Important:

Non-visual constructs must declare:
- `structure = "analysis-only"`
- `accepts_empty_render_output = True`

---

## 5. Computation Layer (Family Modules)

Each family implements its own module:


financial_tools/
indicators/
indicators.py
oscillators/
oscillators.py
constructs/
constructs.py


---

### 5.1 Standard Pattern

Each family follows the same structure:

- Request dataclass
- Line dataclass
- Result dataclass
- Registry (name → method)
- `calculate()` dispatcher

---

### 5.2 Example Flow


request → calculate() → result → controller → chart


---

### 5.3 Result Model

Each result contains:

- name
- title
- index
- time
- timeframe
- params
- lines (0 or more)
- metadata

Important:

- Indicators/oscillators → lines required
- Constructs → lines optional

---

## 6. Controller Integration

### 6.1 Entry Point

`HistoricalChartController.apply_financial_tool(payload)`

---

### 6.2 Dispatch


if indicator → Indicators.calculate(...)
if oscillator → Oscillators.calculate(...)
if construct → Constructs.calculate(...)


---

### 6.3 Output

Controller builds a payload:

- series_list (may be empty)
- behavior (from spec)
- output (from spec)

---

## 7. Panel Integration

### 7.1 Behavior-Driven Routing

Panel uses:

- `output_mode`
- `chart_renderable`

to determine:

- pane target
- rendering
- lifecycle

---

### 7.2 Rendering Rules

| Mode | Behavior |
|------|--------|
| overlay | render on price pane |
| oscillator-pane | create/manage pane |
| non-visual | no rendering |

---

### 7.3 Non-Visual Studies

- no series applied
- still registered
- lifecycle supported
- style disabled

---

## 8. Study Lifecycle

Apply:
- compute result
- apply rendering (if any)
- register study

Edit:
- replace existing instance

Remove:
- remove rendering
- remove from registry

Style:
- only affects renderable studies

---

## 9. FinancialToolManagerWindow

Responsibilities:

- select tool family
- select tool
- edit parameters
- emit apply/save signals

Does NOT:

- compute tools
- manage rendering
- manage panes

---

## 10. Current Capabilities

- indicator computation and rendering
- oscillator pane management
- construct system (overlay / oscillator / non-visual)
- behavior-driven rendering pipeline
- chart-local study lifecycle
- parameter-driven tool configuration

---

## 11. Current Limitations

- construct persistence not implemented
- non-visual studies not visibly represented in UI
- no dependency graph between tools
- no cross-chart synchronization
- no batch analysis pipeline

---

## 12. Design Principles

### Explicit over implicit
Behavior is declared, not inferred.

### Family separation
Each tool family owns its computation logic.

### Rendering independence
Computation does not know about chart layout.

### Chart-local lifecycle
Studies belong to chart sessions, not global state.

---

## 13. Summary

The Financial Tools system provides:

- unified tool specification layer
- scalable family-based computation
- behavior-driven rendering
- support for non-visual analytical tools
- clean separation between computation, rendering, and layout

It is designed to scale toward:

- complex constructs
- analytical pipelines
- future strategy systems

without breaking the charting architecture.