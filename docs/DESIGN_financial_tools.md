# DESIGN — Financial Tools System

Leonardo
Version: v1.18
Date: 2026-05-22
Scope: Indicators, Oscillators, Constructs, Tool Specs, Naming Policy, Controller Integration, Panel Integration, Workspace Integration, Chart Application

---

## 1. Purpose

The Financial Tools system defines how analytical tools are:

- defined in the spec layer
- canonically named in the naming layer
- computed in family modules
- applied to charts through controller → panel → workspace
- optionally persisted as full-dataset artifacts

The system supports three tool families:

- Indicators
- Oscillators
- Constructs

These families share a unified specification model but differ in computation semantics, output structure, and chart behavior.

---

## 2. Core Concepts

### 2.1 Financial Tool

A financial tool is a reusable analytical definition composed of:

- input requirements
- parameters
- computation logic
- canonical output naming
- output structure
- behavior metadata

A financial tool exists independently of any chart session.

### 2.2 Study (Runtime Instance)

A study is a chart-local runtime instance of a financial tool.

Properties:

- tied to a specific dataset
- stored in `ChartStudyRegistry`
- may or may not render on chart
- not part of persistence identity
- pane-agnostic at the study-definition level

A controller-side projection is not the same thing as a chart-local study instance.

One controller projection may legitimately feed multiple chart-local studies when the same tool configuration is applied more than once in one chart session.

That means chart-local `instance_id`, style state, and renderer-facing render keys remain downstream chart-session truth. They are not part of persistence identity and they are not owned by controller compute truth.

### 2.3 Separation of Responsibilities

| Layer | Responsibility |
|---|---|
| Naming | Canonical names, source tokens, instance identity |
| Spec | Metadata, roles, parameter definitions, renderability metadata |
| Family | Computation |
| Controller | Execution, binding resolution, payload construction, compute/render boundary |
| Panel | Study lifecycle, chart-local style, chart-local oscillator policy |
| Workspace | Layout, pane ownership, managed study grouping |
| Renderer | Drawing only |

---

## 3. Tool Families

### 3.1 Indicators

Indicators are overlays on the price chart.

Rules:

- always renderable in principle, subject to signal metadata
- identity is centralized in `ft_naming.py`
- specs resolve output metadata through the naming layer
- chart styling remains downstream

Indicators define data outputs only.
They do not define renderer behavior.

Validated current indicator-family note:

- single-signal overlays: SMA, EMA, TEMA, HMA, KAMA
- multi-signal overlays: BB, HCK, and `peaks_troughs`
- `peaks_troughs` is a price-pane indicator with sparse event-style outputs for confirmed 3/5/7/9/11-bar fractal peaks and troughs
- HCK also emits a non-renderable utility/state output (`vwap_color`) which must not be injected into the chart renderer

### 3.2 Oscillators

Oscillators render in lower panes and are pane-managed.

Rules:

- lowercase only
- parameter-dependent identity encoded in canonical output naming
- output semantics remain computation-only

Oscillators define **data outputs only**.

They do **not** define:

- visual bounds
- threshold levels as renderer behavior
- pane behavior
- rendering logic
- conditional styling

Oscillator visualization is governed downstream by a **chart-local visual policy system**.

Current oscillator output baseline:

| Oscillator | Outputs | Notes |
|---|---|---|
| RSI | `rsi_{period}` | single-line bounded oscillator using the generic RSI-family `70 / 50 / 30` visual guide policy |
| ARSI | `arsi_{period}_{method}`, `arsi_signal_{period}_{method}_{signal_period}_{signal_method}` | Ultimate RSI-style two-line oscillator with configurable `EMA/SMA/RMA/TMA` smoothing and dedicated `80 / 50 / 20` guide levels |
| MFI | `mfi_{period}` | single-line bounded oscillator using the generic RSI-family `70 / 50 / 30` visual guide policy |
| TDI RSI | `tdirsi_fast_ma_*`, `tdirsi_slow_ma_*`, `tdirsi_up_*`, `tdirsi_dn_*`, `tdirsi_mid_*` | multi-line bounded oscillator; band fills are chart-local visual policy |
| SMI | `smi_{k_length}_{d_length}`, `smi_signal_{k_length}_{d_length}` | multi-line signal oscillator with auto range and zero guide |
| OBV | `obv` | unbounded auto-range oscillator |
| Volume | `volume`, `volume_mean_{period}` | histogram volume plus configurable rolling mean line; chart-local renderer/policy owns visual treatment |

ARSI's orange signal/mean line is a static GUI default, not contract truth. The contract/spec/naming layers only define the two runtime outputs and their metadata.

### 3.3 Constructs

Constructs are behavior-driven analytical tools defined by output semantics and runtime naming, not by rendering category.

Key properties:

- runtime-driven output naming
- explicit input roles
- multi-output capable
- chain-safe
- deterministic
- renderability determined by spec metadata and runtime output structure

Constructs may render as overlays, oscillator-pane studies, or non-visual outputs depending on behavior metadata and output semantics.

---

## 4. Output Identity and Renderability

Each runtime output signal has semantic metadata including:

- `signal_type`
- `renderable`
- `analysis_usable`

These are resolved through spec formatting helpers such as:

- `format_output_names(...)`
- `format_output_signals(...)`

### Critical rule

`renderable=True` means a runtime output may be converted into a chart render series.

`renderable=False` means the runtime output must **not** be converted into a chart render series.

### Implications

Non-renderable outputs are still valid runtime outputs.

They may still be:

- persisted
- analyzed
- reused as saved sources
- carried as metadata
- retained as temporary chart-session construct sources when `analysis_usable=True`

They must not be turned into chart series.

### Canonical examples

HCK emits:

- `fast_vwap` → renderable
- `slow_vwap` → renderable
- `vwap_color` → non-renderable utility output

Result:

- only `fast_vwap` and `slow_vwap` become chart series
- `vwap_color` remains non-renderable runtime output

BB emits:

- `bb_middle` → renderable
- `bb_upper_band` → renderable
- `bb_lower_band` → renderable

Result:

- BB is a multi-signal indicator with three rendered overlay lines
- no additional utility output is required for chart rendering

`peaks_troughs` emits:

- `peak_fractal_3`, `trough_fractal_3`
- `peak_fractal_5`, `trough_fractal_5`
- `peak_fractal_7`, `trough_fractal_7`
- `peak_fractal_9`, `trough_fractal_9`
- `peak_fractal_11`, `trough_fractal_11`

Result:

- `peaks_troughs` is a multi-signal renderable indicator with `events` output structure
- the 3-bar pair is default-visible, while the longer fractal pairs remain available as chart-local style visibility choices
- chart rendering for this family is marker-style and spacing remains chart-local style state rather than compute truth


### Universal Trend Classifier dependency contract

`universal_trend_classifier` is a price-pane market-structure classifier. It emits:

- horizontal-range bands and range start/end markers;
- non-renderable boolean state outputs for `uptrend`, `downtrend`, `horizontal_range`, and composites;
- sparse start/end marker prices for directional and range intervals.

Historical UTC consumes confirmed Peaks & Troughs event columns through two independent dependency intents before compute:

- directional trend stream: `peak_fractal_{trend_fractal_window}` and `trough_fractal_{trend_fractal_window}`;
- horizontal range stream: `peak_fractal_{range_fractal_window}` and `trough_fractal_{range_fractal_window}`.

The compatibility `fractal_window` parameter remains an alias for the directional trend stream. The default directional trend selection is `trend_fractal_window=5`; the default horizontal range selection is `range_fractal_window=3`. Advanced column overrides may still be supplied as `trend_peak_column` / `trend_trough_column` and `range_peak_column` / `range_trough_column`.

UTC runtime remains compute-only. It must not open saved artifact files directly and must not own source resolution. Saved Peaks & Troughs artifact lookup, timestamp-safe alignment, and dataframe injection belong to the historical controller/source-resolution boundary. The controller must treat trend and range Peaks & Troughs dependencies as separate logical injection requests, then deduplicate required columns if both streams resolve to the same pair. The current implementation centralizes execution dependency preparation in `utc_dependency_sources.py`; chart apply/save and `ArtifactCalculationService` share that helper, while recovery planning shares only the dependency-intent resolver and stays read-only.

Horizontal range detection uses the range fractal stream only to discover/define a range zone. Once active, range continuation is governed by price acceptance, `hr_break_mode` (`close`, `wick`, or `hybrid`), and pending breakout/reclaim state rather than by requiring more fractals. Historical replay remains sequential: bars are replayed in order and confirmed range swings are fed only when knowable so historical and future realtime behavior can match.

Invalid OHLC/source rows are hard continuity breaks. Historical directional trend detection must run inside contiguous valid-data segments so uptrend/downtrend intervals never bridge NaN or malformed candle/source gaps.

Directional UTC trend semantics are sequential and swing-state based, not fully vectorized:

- uptrends start only at troughs and end only at peaks;
- downtrends start only at peaks and end only at troughs;
- active uptrends continue until their current structural floor is broken or an opposite downtrend is confirmed from the current endpoint peak;
- active downtrends continue until their current structural ceiling is broken or an opposite uptrend is confirmed from the current endpoint trough;
- opposite trends may share exactly one boundary swing/bar under the shared-extreme rule;
- opposite trends must not overlap beyond that shared boundary;
- `hr_trend_max_gap` is not used for directional trend detection and remains horizontal-range continuity metadata.

Shared-extreme examples:

```text
uptrend:    T → ... → P0
                       P0 → T1 → lower P1 → lower T2    downtrend

downtrend:  P → ... → T0
                       T0 → P1 → higher T1 → higher P2   uptrend
```

The render layer must keep treating UTC state outputs as upstream semantics. Renderer code draws already-projected resident-local payload and must not infer trends from candles or Peaks & Troughs markers.

---

## 5. Specification System (`ft_specs.py`)

### 5.1 Role

The spec layer defines metadata only.

It does **not** own:

- computation
- output naming templates
- visual defaults
- renderer behavior
- pane behavior

### 5.2 What specs define

Specs define:

- parameter schema
- input roles
- output structure
- behavior metadata
- renderability metadata
- oscillator semantic guide metadata where applicable

### 5.3 What specs do not define

Specs must not define:

- semantic renderer defaults
- conditional chart behavior
- style defaults
- output naming templates
- pane layout

---

## 6. Naming Policy

Naming authority is centralized.

Responsibilities:

- `ft_naming.py` → canonical source tokens, instance identity, binding-aware naming
- family modules → runtime-emitted output names
- specs → semantic metadata, not naming templates

### Rule

Naming must be:

- deterministic
- lowercase
- chain-safe
- filesystem-safe
- UI-independent
- runtime-driven

The GUI must consume naming; it must not reconstruct naming locally.

---

## 7. Controller Integration

`HistoricalChartController` is the compute/render boundary.

### Controller responsibilities

The controller must:

- resolve all structured construct bindings
- inject bound source data into the working dataframe
- support unary / fast-slow / fast-mid-slow / multi-source constructs
- compute full-dataset results where required
- serialize runtime output metadata
- filter apply-time render series using resolved signal metadata

### Compute/render boundary rule

Computation may run on the **full canonical dataset**.

Rendering must receive **resident-local series only**.

That means:

- full-dataset compute truth remains upstream
- render truth is trimmed at the controller boundary
- renderers must not repair indexing later

### Apply-time filtering rule

Only outputs with `renderable=True` may be converted into `ChartSeries`.

All non-renderable outputs must be excluded from chart rendering even if present in runtime output.

If a tool is chart-renderable but resolves zero renderable outputs, the apply path must fail loudly unless the tool contract explicitly declares `accepts_empty_render_output=True`. There must be no fallback that renders every runtime output.

### Source alignment rule

When constructs consume saved artifacts, source alignment must be deterministic.

Valid alignment requires a shared key such as:

- `ts_ms`
- `time`

Equal row count alone is not considered valid alignment proof.

Positional artifact injection is not an acceptable deterministic alignment strategy.

### Full-dataset integrity rule

Before compute, full-dataset dataframe handling must preserve:

- required OHLCV columns
- monotonic timestamp order
- duplicate rejection
- stable timeline semantics

### Projection identity rule

Controller projection identity represents compute truth, not chart-local render identity.

One controller projection may legitimately be reused by multiple chart-local studies downstream. The controller therefore owns full-study truth and resident-local projections, while panel/workspace consume those projections through chart-local study ids and renderer-facing render keys.

---

## 8. Apply vs Save

### Apply

Apply is a chart-session operation.

Properties:

- compute may run on the full dataset
- rendered series are trimmed to the active resident slice
- no persistence occurs
- chart payload is resident-local only

### Save

Save is a full-dataset persistence operation.

Properties:

- compute runs on the full canonical dataset
- result is persisted without render trimming
- save output is independent of current viewport or resident slice

### Critical distinction

Apply and Save may share compute semantics but they do not share render scope.

Apply is render-scoped.
Save is persistence-scoped.

### Saved artifact metadata sidecars

Saved financial-tool artifacts are CSV-backed persisted data artifacts. A save writes the full-dataset CSV and, for normal CSV-backed artifacts, an adjacent metadata sidecar:

```text
<instance_key>.csv
<instance_key>.meta.json
```

The CSV is the tabular value truth. The `.meta.json` sidecar is the artifact identity, metadata, lineage, fingerprint, and quality truth.

The sidecar must consume existing contract-backed metadata rather than inventing it locally:

- `ToolContract` provides tool family, title, params, behavior, output structure, construct IO, and oscillator visual metadata;
- `ft_specs.py` provides output names/signals, renderability, analysis usability, labels, semantic roles, and value types;
- `ft_naming.py` provides canonical source tokens, saved identity, binding slugs, parameter slugs, and runtime output naming helpers.

Params and bindings are recorded as `explicit` when the save caller supplies them. Legacy or restored metadata may mark them as `inferred` or `unknown`; the metadata must not pretend precision it does not have.

Historical chart save passes explicit params, explicit construct bindings when present, and durable saved-source lineage (`source_artifacts`) to the persistence layer. Temporary chart-session sources are not written as durable lineage artifacts.

Non-renderable utility outputs remain valid persisted outputs. Their sidecar column metadata must preserve `renderable=false`, and if they are not analysis-usable, `analysis_usable=false` and `selectable=false`.

Saved-source selection must consume valid sidecar column metadata when available. `selectable` / `analysis_usable` metadata is the source-selection truth; CSV-header fallback is a compatibility path for legacy, missing, malformed, or incomplete sidecars and must not override valid metadata.

Full-dataset save conversion is shared through the data-layer `result_to_save_dataframe(...)` helper so chart save and save-only artifact calculation preserve timestamps, output ordering, boolean/state outputs, numeric values, and NaN/gap honesty consistently before persistence.

Restore-only metadata backfill may recreate missing/corrupt sidecars from existing CSV files, but it must not rewrite the CSV value artifact and must not become the normal save path.

---

## 9. Panel Integration (Chart Application Layer)

The panel transforms controller outputs into chart-visible chart-local studies.

### 9.1 Responsibilities

The panel is responsible for:

- registering study instances
- translating controller projections back onto chart-local study ids
- applying render series to workspace
- managing chart-local study lifecycle
- managing chart-local style state
- chart-local render-key namespacing for duplicate same-config studies
- reapplying style without recomputation
- seeding chart-local oscillator visual policy
- persisting resolved default styles into study state

### 9.2 Duplicate-study rule

One controller projection may legitimately fan out to multiple chart-local study instances when the same study configuration is applied more than once.

The panel preserves that distinction by:

- keeping chart-local study identity separate from controller compute truth
- mapping projected refreshes back onto chart-local study ids
- namespacing renderer-facing render keys per study instance before workspace apply/reapply

Duplicate same-config studies may therefore share controller compute truth upstream without collapsing into one chart-local study downstream.

### 9.3 Rendering pipeline

Apply-time flow:

`controller → resident-local series/projection → panel → workspace`

Style-time flow:

`existing rendered series or projected resident-local payload → panel → final chart-local style resolution → workspace reapply`

### 9.4 Slice-refresh rule

On resident-slice refresh, the panel must reuse controller-projected resident-local payloads and resolve the final chart-local styled payload once before workspace reapply.

It must not recompute study data, and it must not trigger a second redundant style-reapply pass for the same slice refresh.

### Critical rule

The panel must never recompute study data for style changes.

Style changes must remain visual-only.

### 9.5 Style layer

After controller filtering, rendering enters chart-local style resolution.

This includes:

- persisted study style state
- per-signal overrides
- per-fill overrides
- style modules

This layer:

- operates only on renderable outputs
- does not access computation internals
- does not modify runtime data
- does not affect persistence
- may expand one logical chart-local study into multiple explicit renderer-facing series/fills when historical conditional rendering requires segmented visual payload

### 9.6 Default-style persistence rule

Static defaults are resolved at apply-time and persisted into `ChartStudyInstance.style`.

This is critical.

The panel must not leave semantic defaults implicit in renderer fallback behavior.

If defaults are missing from persisted chart-local study state, upstream style resolution is broken.

---

## 10. Style Modules (Dynamic Rendering Layer)

Style modules provide dynamic, condition-driven visual behavior.

Examples:

- conditional line color
- conditional fill color
- future state-based visual logic

Properties:

- applied after static style resolution
- evaluated at render time
- operate on rendered series only
- do not affect computation
- do not affect output structure

### HCK example

HCK uses conditional style modules seeded at apply-time, but its validated chart behavior is **historical segmented conditional rendering**, not whole-study latest-state tinting.

Condition:

`fast_vwap > slow_vwap`

Effect:

- bullish segments of both rendered VWAP lines are green
- bearish segments of both rendered VWAP lines are red
- bullish segments of the band fill are green
- bearish segments of the band fill are red
- crossover continuity is resolved upstream in panel/resolver payload construction

Important rule:

- the renderer does not infer HCK semantics
- the panel/style-resolver layer expands the logical HCK study into explicit segmented renderer-facing payload
- the utility state output is not itself rendered

---

## 11. Oscillator Visual Policy

Oscillator visualization introduces a separate **chart-local visual policy layer**.

This layer is distinct from:

- spec
- computation
- static defaults
- style modules

### Purpose

Visual policy defines how oscillator data is interpreted inside a pane.

Examples:

- fixed bounds for RSI-family oscillators
- auto-fit behavior for unbounded oscillators
- guide levels
- threshold-aware line coloring
- pane-local vertical drag
- pane-level fills and levels

### Ownership

- panel → seeds defaults
- workspace → persists policy
- pane → applies pane behavior
- renderer → executes policy

### Critical rule

Oscillator visual policy is:

- chart-local
- pane-scoped
- visual-only
- not part of spec execution
- not part of computation
- not part of artifact persistence

---

## 12. Relationship Between Defaults, Style, and Policy

These are separate layers and must remain separate.

### Static defaults

Defined in `study_style_defaults.py`

They define default appearance.

### Persisted study style

Stored in `ChartStudyInstance.style`

It defines chart-local study truth for styling.

### Style modules

Provide conditional appearance logic.

### Oscillator visual policy

Defines pane-level interpretation behavior such as bounds and levels.

### Rule

Defaults define appearance.
Style defines chart-local overrides.
Policy defines pane interpretation.

These must not be collapsed into one layer.

---

## 13. Workspace Integration

Workspace owns:

- pane registry
- pane ordering
- study-to-pane mapping
- managed overlay-study grouping
- oscillator pane policy state
- batched reapply of final panel-resolved resident-local payloads

Rules:

- layout is workspace-owned
- studies do not own pane placement
- 1 oscillator study → 1 pane
- 1 study → N series
- 1 overlay study → 1 logical study entry
- 1 overlay study → N render series
- workspace consumes explicit chart-local study ids and renderer-facing render keys from the panel; it does not infer chart-local identity from controller compute truth

Duplicate same-config studies may share controller compute truth upstream, but workspace must still keep their pane/render state separate downstream.

Workspace persists pane/layout behavior, not computation truth.

---

## 14. Renderer Integration

Renderers are dumb execution layers.

They must consume:

- resident-local series
- chart-local style state
- pane-level visual policy
- any explicit segmented renderer-facing payload already derived upstream

They must not:

- recompute values
- repair indexing mistakes
- define semantic defaults
- derive study semantics such as HCK fast/slow state on their own
- bridge NaN gaps
- reinterpret non-renderable outputs
- mutate runtime data

### Gap honesty rule

Invalid values, warm-up gaps, and segmented conditional regions must remain visually honest.

Renderers must break segments on invalid data rather than smoothing or connecting across gaps.

---

## 15. Current Capabilities

The current system now supports:

- indicators aligned with naming/spec/runtime contracts
- validated single-signal and multi-signal indicator rendering for the current family (including BB, HCK, and `peaks_troughs`)
- oscillators aligned with chart-local visual policy
- constructs aligned with runtime naming and deterministic source resolution
- controller-side renderable-signal filtering
- multi-output construct support
- temporary chaining from non-renderable `analysis_usable` outputs without rendering those outputs
- chart-local style persistence
- style-only reapply without recomputation
- duplicate same-config chart-local studies over shared controller projection truth
- chart-local render-key namespacing for duplicate-study safety downstream
- resident-local projected-study reapply without recomputation
- conditional rendering via style modules
- historical segmented conditional rendering
- crossover-safe upstream segmented payload construction for conditional overlay studies such as HCK
- bounded oscillator rendering
- pane-local oscillator interaction
- resident-local render payload enforcement
- full-dataset apply/save distinction
- shared full-dataset save conversion through `result_to_save_dataframe(...)`
- sidecar-driven saved-source selection with legacy CSV-header fallback
- shared UTC dependency preparation for execution and shared UTC dependency-intent resolution for recovery planning
- CSV + `.meta.json` sidecar persistence for saved OHLCV and financial-tool artifacts

---

## 16. Architectural Summary

The Financial Tools system now enforces:

- single naming authority
- runtime-driven construct truth
- spec-driven UI and semantic metadata
- controller-side renderable signal filtering
- controller-owned compute/render boundary
- panel-side chart-local study/style ownership over shared controller projections
- panel/resolver-side segmented renderer payload derivation for historical conditional studies
- workspace-side pane/grouping application from explicit chart-local payloads
- persisted default-style truth in study state
- chart-local marker-style event rendering for indicator studies such as `peaks_troughs`
- chart-local grouped Above/Below spacing controls for event-style marker families
- chart-local oscillator visual policy
- dynamic oscillator default-style resolution for parameterized output names
- Ultimate RSI-style ARSI with main and signal outputs
- Volume oscillator rendering as histogram plus configurable rolling mean line
- strict separation between computation and visualization
- renderer as execution-only

---

## 17. Validation Basis

This design is aligned with the validated implementation across:

- indicator family runtime behavior, including current multi-signal overlays and event-style marker overlays
- oscillator runtime behavior
- construct runtime naming and gap behavior
- controller apply/save boundary behavior
- panel duplicate-study identity, style persistence, and reapply behavior
- workspace pane/grouping ownership from explicit chart-local ids and render keys
- renderer resident-local execution behavior
- saved artifact sidecar metadata generated from the contract/spec/naming surfaces without altering chart render semantics
- explicit params/bindings/source lineage on newly saved artifacts where supplied by the save caller

The enforced architectural flow is:

`spec → naming → compute → controller → panel → workspace → renderer`

with the following invariants:

- compute truth stays upstream
- render truth is resident-local
- chart-local identity stays downstream of controller compute truth
- style truth is chart-local
- policy truth is pane-local
- renderer does not reinterpret semantics
---

## 16. Refactor Baseline — 2026-04-20
This section records the current source layout after the financial-tools refactor. It is an implementation map, not a new ownership model.

### 16.1 Stable public façades

The following public imports remain the stable entrypoints:

```python
from leonardo.financial_tools.ft_naming import ...
from leonardo.financial_tools.ft_specs import ...
from leonardo.financial_tools.indicators.indicators import Indicators, IndicatorRequest
from leonardo.financial_tools.oscillators.oscillators import Oscillators, OscillatorRequest
from leonardo.financial_tools.constructs.constructs import Constructs, ConstructRequest
```

The façade files preserve public API compatibility. Their internals delegate to runtime/support packages.

### 16.2 Current package layout

```text
src/leonardo/financial_tools/
    ft_naming.py                 # public naming façade
    ft_specs.py                  # public specs façade

    tool_contracts/
        contracts.py             # typed structural contracts
        registry.py              # canonical contract registry
        validation.py            # contract validation
        manifests/
            indicators.py
            oscillators.py
            constructs.py

    naming_runtime/
        tokens.py
        hashing.py
        indicators.py
        oscillators.py
        constructs.py
        constructs_core.py
        bindings.py
        persistence.py
        registry.py

    specs_runtime/
        models.py
        inputs.py
        params.py
        behavior.py
        capabilities.py
        resolvers.py
        builder.py
        registry.py

    indicators/
        indicators.py            # bridge / public compute façade
        indicators_runtime/
            sma.py
            ema.py
            tema.py
            hma.py
            kama.py
            bb.py
            hck.py
            peaks_troughs.py
            strategy.py
            common.py
            contracts.py

    oscillators/
        oscillators.py           # bridge / public compute façade
        oscillators_runtime/
            rsi.py
            arsi.py
            tdirsi.py
            smi.py
            mfi.py
            obv.py
            common.py
            contracts.py

    constructs/
        constructs.py            # bridge / public compute façade
        constructs_runtime/
            dynamic_binning.py
            derivative.py
            angle.py
            braids.py
            braid_instability.py
            delta.py
            trap_area.py
            percent_span_angle.py
            angle_momentum.py
            common.py
            contracts.py
```

### 16.3 Contract-backed truth chain

The current truth chain is:

```text
ToolContract manifests
→ family bridge/runtime compute
→ ft_naming identity
→ ft_specs metadata projection
→ controller execution/render filtering
→ panel chart-local study/style truth
→ workspace pane contracts
→ renderer execution
```

Rules that are now considered fixed:

- every supported tool must have a `ToolContract`;
- naming/spec runtime modules must not import compute bridges or compute runtime modules;
- specs derive output metadata from naming/contract data, not ad hoc templates;
- runtime output keys must match naming resolver expectations;
- controller and GUI consume canonical identity, they do not reconstruct it locally.

### 16.4 Financial-tools bugfix baseline

The naming runtime now treats missing non-construct binding slugs as `"default"`. This preserves indicator/oscillator instance identity such as:

```text
sma__default__period-14
rsi__default__period-14
obv__default
```

Persistence helpers also normalize a missing binding slug defensively before slug processing. This prevents `NoneType.replace` failures at apply/save identity construction boundaries.

### 16.5 Validation required before adding tools

Before a new financial tool is accepted:

1. Add or update its `ToolContract` manifest entry.
2. Implement compute in the family runtime package.
3. Expose it through the family bridge registry.
4. Confirm naming output and runtime output keys match.
5. Confirm specs resolve parameters, behavior, capabilities, and output signals from the contract layer.
6. Run contract validation and representative runtime smoke tests.
7. Confirm non-renderable outputs are excluded from chart render payloads.
