# Construct Naming & Behavior Policy (Leonardo)

Version: v1.8
Date: 2026-05-28
Scope: Construct runtime naming, input-role semantics, multi-output behavior, saved identity, metadata sidecars, execution environment context, renderability boundary, and controller/UI integration

This document defines the canonical rules for:

- construct output column naming
- construct input role semantics
- multi-output construct behavior
- saved construct artifact identity
- runtime behavioral invariants
- controller/UI integration boundaries for constructs

It reflects the current runtime ground truth across the construct family, the shared naming layer, spec metadata, and the historical chart controller boundary.

---

## 1. Core Principles

All construct naming and behavior must be:

- lowercase
- deterministic
- chain-safe
- filesystem-safe
- independent of UI or rendering
- independent of execution environment context
- derived from runtime logic, not spec templates

Naming authority is centralized in:

- `ft_naming.py` → token construction, binding-aware identity, saved artifact identity
- construct runtime modules → emitted runtime outputs

### Runtime rule

Runtime is the single source of truth for emitted construct outputs.

Specs may describe roles, semantic metadata, and renderability, but they do not define naming templates.

### Separation rule

Constructs define analytical output truth.
The chart layer consumes that truth downstream.
Renderers must never reinterpret construct naming or invent construct semantics.

---

## 2. Source Tokens

A source token represents a concrete data lineage.

Examples:

- `close`
- `ema_14_close`
- `rsi_14_close`

Rules:

- token must reflect actual data lineage
- token must not reflect UI labels
- token must be produced through canonical naming helpers
- token must be chain-safe

This prevents display labels or UI-friendly aliases from leaking into runtime identity.

---

## 3. Unary Constructs

Unary constructs operate on one source.

### Canonical format

`<source>__<operation>`

### Active unary operations

| Construct | Outputs |
|---|---|
| derivative | `__d1`, `__d2` |
| angle | `__ang` |

### Examples

- `close__d1`
- `ema_14_close__d2`
- `close__ang`

### Notes

The following are not active canonical identities:

- `__slp`
- `__ang_pct`

Those are deprecated or removed from the active runtime contract.

---

## 4. Binary / Pair Constructs

### Delta

Canonical forms:

- `<fast>_<slow>_delta`
- `<fast>_<slow>_delta_pct`

Examples:

- `ema_9_ema_21_delta`
- `ema_9_ema_21_delta_pct`

Rules:

- delta is always directional: `fast - slow`
- percent mode uses `slow` as the reference
- no legacy `__dlt__` naming remains

Directionality is part of the feature identity, not a presentation choice.

---

## 5. Multi-Source Constructs

All multi-source constructs use canonical source-token concatenation.

### Token construction

`<token1>_<token2>_<token3>`

Generated via canonical naming helpers, not via ad hoc string concatenation in the UI or controller.

---

## 6. Braids

### Outputs (runtime)

Let ``base`` be the braid token (constructed from the ordered input set).

- ``base`` → **ambient state** (categorical ordering identity; `1..6`, or `NaN` on ties / invalid rows)
- ``base_width`` → total braid envelope spread: `max(fast, mid, slow) - min(fast, mid, slow)`
- ``base_compression`` → minimum pairwise separation: `min(|fast-mid|, |fast-slow|, |mid-slow|)`

Example base:

- `ema_9_ema_13_ema_21`

Example outputs:

- `ema_9_ema_13_ema_21`
- `ema_9_ema_13_ema_21_width`
- `ema_9_ema_13_ema_21_compression`

### Ambient state values (semantic meaning)

These values represent the ordered relationship between the three inputs:

- `1`: slow > mid > fast
- `2`: slow > fast > mid
- `3`: fast > slow > mid
- `4`: fast > mid > slow
- `5`: mid  > fast > slow
- `6`: mid  > slow > fast

UI may present these as human-readable “ambient codes” (e.g. `F>M>S`).
This is **display-only** and must not affect naming or saved identity.

### Tie handling

- ties produce `NaN` in the raw ambient state by default
- with `tie_policy="carry"`, the most recent non-null ambient state is forward-filled
- with `tie_policy="drop"`, ties remain `NaN`

### Renderability policy

Braids are **multi-output**, but not every output is intended to be chart-rendered.

- the ambient state output (`base`) is chart-renderable
- `*_width` and `*_compression` are **analysis outputs** (non-renderable by default), but remain valid runtime outputs for persistence and chaining

The controller must convert **only** `renderable=True` outputs into chart series.
Non-renderable braid outputs must never become chart series, even though they are valid runtime outputs.


## 7. Braid Instability

Canonical form:

`<base>_inst_{n}`

Example:

- `ema_9_ema_13_ema_21_inst_5`

### Runtime behavior

Braid instability derives from braid-state transitions over a window.

Important invariant:

- braid instability semantics must remain aligned with braid-state runtime logic
- duplicated braid-state logic across implementations is discouraged
- output meaning comes from runtime state progression, not from renderer interpretation

---

## 8. Trap Area

Trap area emits pairwise area outputs such as:

- `<fast>_<slow>_trapA`
- `<fast>_<mid>_trapA`
- `<mid>_<slow>_trapA`

### Runtime behavior

Trap area is a segmented cumulative construct.

Critical validated behavior:

- NaN gaps must break accumulation segments
- a gap row must remain NaN
- the first valid bar after a gap starts a new segment at `0.0`
- accumulation must not bridge across invalid regions

Gap honesty is part of the runtime contract.

---

## 9. Window-Based Constructs

### Percent Span Angle

Canonical form:

`<source>_ang_pct_span_{window}`

Examples:

- `close_ang_pct_span_5`
- `ema_50_ang_pct_span_8`

### Rules

- window is part of feature identity
- output requires a contiguous valid window
- invalid or gapped windows must not be bridged
- legacy `percent_angle` naming is replaced by this canonical form

This construct is explicitly window-identity-driven.

---

## 10. Momentum Constructs

### Angle Momentum

Canonical form:

`<source>_ang_mtm_{n}`

Example:

- `close_ang_mtm_6`

### Rules

- not percent-based
- measures angle change per bar
- identity includes window length
- semantics remain numeric/runtime-defined, not renderer-defined

---

## 11. Construct Input Roles

Construct inputs are structured roles, not generic free-form parameters.

### Supported role models

| Variant | Roles |
|---|---|
| unary | `source` |
| fs | `fast`, `slow` |
| fms | `fast`, `mid`, `slow` |
| multi | `source_columns` |

### Rules

- roles are explicit and mandatory
- construct outputs may be selected as construct sources when the contract marks the source family as allowed and the selected output is analysis-usable
- UI must use structured selectors
- roles must not be free-form text identity
- controller must resolve bindings before runtime execution

---

## 12. Multi-Output Behavior

Constructs may emit one or many outputs.

Examples:

| Construct | Output count |
|---|---|
| braids | 3 |
| delta (multi-pair) | N |
| trap_area | 1–3 |
| angle_momentum | N |

### Rules

- each output has its own canonical runtime name
- UI and controller must support multi-series emission
- output identity comes from runtime, not from spec templates
- multi-output behavior is first-class, not an exception

---

## 13. Renderability and Chart Application Boundary

Constructs may be chart-renderable, analysis-only, or mixed-output depending on runtime output structure and spec metadata.

### Rules

- construct runtime modules emit output truth
- spec metadata determines semantic renderability
- the controller may only convert outputs with `renderable=True` into chart series
- non-renderable outputs remain valid runtime outputs but must not be injected into the render layer

### Apply vs Save

Constructs follow the same full-dataset boundary as the rest of the financial-tools system:

- **Apply** computes on the full canonical dataset and trims chart payloads to the active resident slice
- **Save** computes on the full canonical dataset and persists full-dataset output unchanged

### Important boundary

The controller must not rename runtime construct outputs while translating them into downstream chart payloads.

Naming truth stays upstream.
Render truth becomes resident-local only at the controller boundary.

Construct execution may receive `ToolExecutionContext`, but that context is not construct naming truth and is not saved artifact identity.

### UTC dependency preparation boundary

`universal_trend_classifier` remains compute-only. Historical apply/save paths prepare required Peaks & Troughs columns before runtime dispatch through a shared data-layer helper. That helper resolves directional and range dependency intents, honors legacy `fractal_window` fallback and explicit trend/range overrides, loads the saved `peaks_troughs` artifact for the same market partition, and aligns required columns by `ts_ms` or `time` only.

Recovery planning uses the same dependency-intent/required-column resolver but remains read-only. It may classify missing artifacts, missing columns, missing join keys, or duplicate join keys as blockers, but it must not inject columns or compute UTC.

---

## 14. Saved Construct File Identity

Saved construct artifacts use deterministic file identity.

### Format

`{construct_key}__{binding_slug}__{param_slug}__h{hash8}.csv`

### Components

- `construct_key` → tool identity
- `binding_slug` → resolved input-role identity
- `param_slug` → relevant params only
- `hash` → deterministic uniqueness

### Examples

- `delta__fast-ema_9_close__slow-ema_21_close__mode-pct__h123abcd.csv`
- `braids__F-ema_9_close__M-ema_13_close__S-ema_21_close__h91ab23cd.csv`

### Rules

- saved identity must be deterministic
- irrelevant params must not pollute identity
- role binding is part of saved identity
- the deterministic `__h<hash8>` suffix is required for active construct saved identity
- saved identity must remain chain-safe and filesystem-safe
- execution environment must not be included in saved construct file identity

### Metadata sidecar

Every saved construct CSV must have an adjacent metadata sidecar:

```text
<construct_instance_key>.csv
<construct_instance_key>.meta.json
```

The CSV remains the construct value artifact. The `.meta.json` sidecar carries artifact identity and metadata, including:

- `unique_id`;
- deterministic `artifact_id`;
- globally scoped `artifact_uid`;
- market identity;
- CSV and metadata relative paths;
- first/last `ts_ms` plus UTC and `Europe/Rome` display timestamps;
- output columns and per-column renderability / analysis usability;
- construct `tool_key`, `instance_key`, params, and role bindings where available;
- explicit params and role bindings for newly saved artifacts when supplied by the save caller;
- construct IO metadata from `ToolContract`;
- lineage, fingerprint, quality, and extension metadata.

For newly saved constructs, params and role bindings should be written as explicit metadata by the save path. For legacy/restored sidecars, params and bindings may be marked as `inferred` or `unknown`. Filename parsing is fallback only and must not be treated as full construct truth when it cannot prove role-binding semantics.

---

## 15. Execution Environment Context

Construct requests carry `ToolExecutionContext` just like indicators and oscillators.

Current environments:

- `historical`
- `realtime`

Default is `historical`.

This context tells the runtime how a specific execution is being called. It does not define construct output names, does not alter role bindings, does not enter `param_slug`, and does not participate in deterministic saved filename construction.

Contracts/specs describe which environments a construct supports. The family bridge validates support before dispatching to the runtime. A construct runtime may inspect context only when the computation genuinely needs environment-aware behavior.

## 16. Naming vs Runtime Responsibility

| Concern | Owner |
|---|---|
| token construction | `ft_naming.py` |
| output naming | construct runtime modules |
| naming-aware output metadata | `ft_specs.py` |
| UI display text | GUI layer |

### Rule

Specs may describe roles and metadata.
Specs must not define output naming templates.

---

## 17. Runtime Behavioral Invariants

The construct system enforces these runtime invariants:

- runtime is the single source of truth
- naming is centralized
- constructs are chain-safe
- roles are explicit
- controller resolves all bindings
- invalid windows are not bridged
- NaN gaps remain visually and numerically honest
- output identity is derived from runtime emission

### Determinism rule

Constructs must be reproducible from the same ordered input dataframe and resolved bindings.

### Alignment rule

Saved construct sources must be aligned by shared key data such as `ts_ms` or `time`.

Equal row count alone is not considered valid alignment proof.

Positional artifact injection is not a valid deterministic alignment strategy.

### Data Manager Construct Batch policy

Generic Data Manager Construct Batch supports batch-friendly construct expansion only:

- unary `derivative`;
- unary `angle`;
- unary `percent_span_angle`;
- unary `angle_momentum`;
- binary `delta`, reported as `delta = minuend - subtrahend`.

The planner consumes structured saved artifact metadata rather than display labels. Source eligibility is based on `selectable` and `analysis_usable`; non-renderable but analysis-usable outputs may be valid sources, while non-selectable utility outputs are blocked. Delta candidates require timestamp overlap/common range evidence between the fixed and variable sources. Equal row count alone is not alignment proof.

Generic batch does not support `braids`, `braid_instability`, `trap_area`, or `dynamic_binning`. Braids, braid instability, and trap area require curated topology templates rather than broad source expansion. Dynamic binning is a grouped analysis workflow and remains outside one-source/per-recipe batch generation.

---

## 18. Deprecated / Removed Patterns

The following are not valid in the current system:

- `__slp`
- `__dlt__`
- `__ang_pct` as a primary identity
- role-prefixed naming as runtime output identity
- spec-driven naming templates

Deprecated identity must not be revived in UI, controller, or docs.

---

## 19. Controller and UI Integration Rules

The construct system depends on strict upstream integration behavior.

### Controller responsibilities

The controller must:

- resolve structured input bindings
- align external construct sources deterministically
- reject unsafe source joins
- pass runtime outputs through without renaming them
- filter render payloads using resolved renderability metadata
- preserve full-dataset compute truth while emitting resident-local chart payloads

### UI responsibilities

The UI must:

- use structured role selectors
- consume canonical output names
- avoid inventing naming templates
- treat construct outputs as runtime truth
- avoid treating chart-local labels as naming authority

---

## 20. Final State

The construct system is now:

- runtime-driven
- naming-consistent
- role-explicit
- multi-output capable
- chain-safe
- gap-honest
- deterministic

It defines the valid naming and behavior contract for constructs in Leonardo.

---

## 21. Validation Basis

This README is aligned with the documented implementation and architecture across:

- construct runtime output emission
- `ft_naming.py` canonical naming and saved identity rules
- `ft_specs.py` role structure and semantic metadata
- controller-side binding resolution and deterministic source alignment
- Core full-dataset integrity and apply/save boundary rules

No stale construct naming patterns, deprecated identities, or conflicting runtime rules are retained in this document.
---

## 22. Refactored Construct Implementation Map — 2026-04-20
The construct family is now physically split into a public bridge plus runtime modules.

```text
src/leonardo/financial_tools/constructs/
    constructs.py                 # public compute bridge / registry dispatch
    DynamicBinner.py              # existing support class
    VariationAnalyzer.py          # existing support class
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

Contract/naming/spec ownership sits outside the family runtime:

```text
financial_tools/tool_contracts/manifests/constructs.py
financial_tools/naming_runtime/constructs.py
financial_tools/naming_runtime/bindings.py
financial_tools/naming_runtime/persistence.py
financial_tools/specs_runtime/
```

### Fixed rules after refactor

- `constructs.py` remains the public bridge.
- Runtime modules emit canonical construct output names.
- Specs describe roles and renderability; they do not define construct naming templates.
- Controller resolves structured source bindings before execution.
- Controller filters renderability but does not rename runtime outputs.
- Saved identity is built through naming runtime helpers.
- active construct persistence identity includes deterministic hash suffixes and excludes execution environment context.
- Saved construct CSVs use adjacent `.meta.json` sidecars for artifact identity, params/bindings, output metadata, lineage, and quality metadata. Valid sidecar column metadata supplies source-selection truth where available: selectable analysis outputs may be reused as construct sources, while non-selectable utility outputs remain persisted but hidden from source selection.
- Execution environment context is validated by the construct bridge and excluded from naming/persistence identity.
- Construct source alignment requires deterministic keys such as `ts_ms` or `time`.
- Gap honesty remains a runtime contract for trap area, windowed angle families, and segmented outputs.

### Validation focus

Representative construct validation must include:

- unary: `derivative`, `angle`;
- directional pair: `delta` absolute and percent;
- multi-source: `braids`, `braid_instability`;
- segmented/gap-sensitive: `trap_area`;
- windowed: `percent_span_angle`, `angle_momentum`;
- non-visual: `dynamic_binning`.
