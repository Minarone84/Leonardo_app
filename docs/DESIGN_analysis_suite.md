# Analysis Suite Design

Version: v0.2
Status: AS8 accepted backend MVP plus future architecture
Date: 2026-05-29

## Purpose

This document defines the first Analysis Suite architecture for POIs, event
families, roads, outcomes, false-signal classes, genome states, and genome
paths.

AS8-AUDIT established the design boundary. AS8 implements the first backend
POI/family planner within that boundary. The accepted AS8 backend does not add
GUI controls, persistence, white-box rule discovery, backtesting, model
training, signals, neural agents, Decisor logic, artifact calculation, recipe
execution, Analysis Database mutation, or OHLCV repair.

## Current Foundation

The accepted Analysis Suite foundation is read-only:

- AS1: `AnalysisSuiteDatasetReadinessService` reports Analysis Database
  readiness, `strict_ready`, `can_preview`, source drift, topology/geography,
  and manifest/dataframe health.
- AS2: `AnalysisSuiteWindow` displays AS1 readiness reports from
  `Analysis -> Analysis Suite` while Data Manager remains the preparation
  workflow.
- AS3: `AnalysisSuiteDataframePreviewService` provides bounded Head/Tail
  dataframe previews with service-enforced row limits.
- AS4: `AnalysisSuiteWindow` calls AS3 for bounded preview and does not load
  `dataframe.csv` directly.
- AS5: `AnalysisSuiteTargetPlanner` previews future return and future direction
  labels with leakage metadata marking outputs as `target_only`,
  `future_derived`, and `feature_eligible = false`.
- AS6: `AnalysisSuiteFeatureSetPlanner` lists manifest-derived feature
  candidates, validates selected features, and rejects target/future-derived
  leakage columns. Manifest/artifact metadata remains feature truth, not raw
  CSV headers.
- AS7: `AnalysisSuiteDiagnosticReportService` composes AS1, AS5, and AS6
  reports into JSON-safe pre-analysis coherence reports.
- AS8: `AnalysisSuitePoiFamilyPlanner` previews POI occurrences and POI
  family membership from prepared Analysis Database columns with bounded
  JSON-safe reports.

AS8 consumes AS1 readiness or optional AS7 diagnostic context. It remains
backend-only, read-only, and non-persistent.

## Manifesto Direction

Leonardo does not forecast raw values first. Leonardo forecasts conditions.

The Analysis Suite direction is:

- What condition is forming?
- What POI family is approaching?
- If this POI spawns, what roads can open?
- How reliable are those roads?
- What happened before similar cases?
- What happened after similar cases?

Core operating phrase:

White boxes discover the roads. Backtests validate the roads. Neural agents
refine the roads. The Decisor chooses the journey.

The operating sequence remains:

1. Database readiness.
2. Target/label coherence.
3. Feature-set legality.
4. Diagnostic setup coherence.
5. POI / event-family / road / genome architecture.
6. White-box rule discovery.
7. Research Suite validation.
8. Neural refinement.
9. Decisor selection.

AS8 is the first backend foundation for step 5. It remains limited to typed
POI/family occurrence preview.

## World-Line Model

The first dimension is time.

The World Line is the ordered sequence of encoded market states over time.
Each timestamp is not only a candle. It is an encoded market condition.

A world-line state may include:

- OHLC and explicit Volume artifact context.
- Peaks & Troughs events such as `peak_fractal_7` or `trough_fractal_7`.
- UTC / Universal Trend Classifier state such as uptrend, downtrend,
  horizontal range, transition, breakout, or reclaim context where available.
- Braids state such as ambient state, width, and compression.
- Indicators, oscillators, constructs, deltas, angles, derivatives, and angle
  momentum.
- Future variation states or dynamic bins when those systems are designed.
- Topology markers and lifecycle markers.

The World Line is the substrate for POI detection, family membership,
pre-event path analysis, post-event road analysis, and later white-box
discovery.

## POI Definition

A POI is a meaningful topology or event point in the World Line.

A POI is not merely a dataframe row. It is a typed event anchored to a
timestamp with source metadata, provenance, and knowability semantics.

Examples:

- T7 trough from `trough_fractal_7`.
- T7 peak from `peak_fractal_7`.
- UTC transition.
- Braid compression.
- Braid expansion.
- Range breakout.
- Trend exhaustion.
- Volatility expansion.

Required POI metadata for future implementation:

- `poi_id` or stable generated identifier for the preview scope.
- `poi_type`, for example `t7_trough`, `t7_peak`, `utc_transition`,
  `braid_compression`, or `range_breakout`.
- `source_columns`.
- `source_family`, `tool_key`, and source artifact/manifest lineage when
  available.
- `anchor_ts_ms`, the market timestamp the event describes.
- `event_ts_ms`, the event row timestamp used for event-centered analysis.
- `confirmation_ts_ms`, when the event becomes knowable, if it differs from
  the anchor timestamp.
- `parameters`, including fractal window or threshold settings.
- `warnings`, `blockers`, and source diagnostics.

Knowability matters. A confirmed fractal can describe an earlier bar while
becoming knowable later. Future analysis must preserve both the anchor
timestamp and the confirmation timestamp to avoid using future-confirmed
events as if they were known at the anchor.

## Event Family And Subfamily

An Event Family is a structured classification of POIs that share type,
context, and market-state conditions.

Example:

- POI type: T7 trough.
- Family: T7 trough inside UTC bullish transition.
- Subfamily: T7 trough with braid compressed, RSI recovering, close below
  SMA50, and delta narrowing.

Families and subfamilies are not model outputs. They are rule-defined event
groupings used to compare similar world-line states.

Future family definition metadata:

- `family_id` or generated preview identifier.
- `name`.
- `poi_type`.
- Required context predicates.
- Optional context predicates.
- Exclusion predicates.
- Required source columns/features.
- Compatible timeframe/market constraints if needed.
- Pre-event and post-event window requirements.
- Leakage and knowability constraints.
- Version/schema.

AS8 defines family membership with explicit rules, not with free-form GUI
labeling or raw header matching.

## Road Definition

A Road is a post-POI outcome path/class.

Roads are outcome classes, not trading signals. They describe what happened
after an event; they do not say to buy, sell, hold, size a position, or route
an order.

Example roads:

- Strong continuation.
- Weak bounce.
- Range continuation.
- Failed signal.
- Reversal.
- Exhaustion.
- Breakout follow-through.

Road assignment should be based on measurable post-event outcome facts and a
declared post-event window. Road classes must be reproducible from data and
definition metadata.

## Outcome Definition

An Outcome is a measurable post-event fact.

Examples:

- Future return over `N` bars after the event or confirmation.
- Max favorable excursion.
- Max adverse excursion.
- Time to threshold.
- Reached threshold yes/no.
- Failed before target yes/no.
- Duration.
- Volatility expansion or contraction after the POI.
- Range continuation or range break after the POI.

Outcomes are event-centered. AS5 targets are generic future labels aligned to
each timestamp. Future outcome analysis is measured relative to POI
occurrences and families, and may reuse AS5-style future-return or direction
logic without becoming generic per-row labels.

## False-Signal Class

A false-signal class is a structured failure mode for a POI or family.

Examples:

- POI appears but no movement follows.
- Movement starts and immediately reverses.
- Breakout fails.
- Trough becomes continuation down.
- Peak becomes continuation up.
- Topology contradiction appears after the event.

False-signal classes are not runtime errors. They are event outcome classes
used for later reliability analysis and road validation.

## Genome Definition

A Genome is a symbolic or encoded market-state vector at timestamp `t`.

Example fields:

- `UTC_state = bullish_transition`.
- `braid_state = compressed`.
- `T7_context = near_trough`.
- `RSI_state = recovering_low`.
- `HCK_state = bullish_shift`.
- `Bollinger_state = lower_rejection`.
- `delta_close_ema50 = negative_narrowing`.
- `variation_state = improving`.

AS8 defines the concept. Full genome encoding should be designed later in
AS9-AUDIT because it requires explicit encoding policy, binning policy,
variation descriptors, symbolic vocabularies, and leakage controls.

Genome inputs must come through AS6-validated feature metadata and must not
consume target outputs, future-derived labels, unknown raw CSV headers, or
feature-ineligible columns.

## Genome Path

A Genome Path is a sequence of genome states:

```text
G(t-k), ..., G(t)
```

It is used for pre-POI anticipation and for comparing how similar market-state
paths evolved before known POI families.

Example:

```text
The 12 bars before a T7 trough inside UTC bullish transition.
```

Genome paths must preserve order, timestamps, missing-state policy, and
knowability. Future AS9 implementation should decide whether paths are encoded
as symbolic tokens, binned numeric descriptors, sparse state dictionaries, or a
hybrid representation.

## Event Windows

AS8 architecture needs explicit windows:

- `pre_event_window_bars`: number of rows before the event or prediction
  timestamp used to describe the pre-event path.
- `post_event_window_bars`: number of rows after the event or confirmation
  timestamp used to measure outcomes and roads.
- `anchor_ts_ms`: market timestamp described by the POI.
- `event_ts_ms`: event row used by the event planner.
- `confirmation_ts_ms`: timestamp when the event is knowable, if delayed.
- `outcome_start_ts_ms`: timestamp where post-event measurement begins.
- `outcome_end_ts_ms`: last timestamp included in the outcome window.

Default decision-safe behavior for delayed events should measure actionable
post-event outcomes from `confirmation_ts_ms`. Retrospective topology analysis
may also report anchor-based outcomes, but that distinction must be explicit.

Last-window rows with insufficient future data should be unavailable rather
than silently filled.

## Relationship To AS1-AS7

AS1:

- Owns dataset readiness and `can_preview`.
- AS8 blocks when AS1 says the dataset is not safely consumable.

AS3/AS4:

- Own bounded dataframe row preview.
- AS8 should not use GUI preview as a data source.

AS5:

- Defines generic target/label preview.
- Future outcome work in this architecture is POI/event-centered and may reuse
  AS5-style formulas without becoming generic per-row labels.

AS6:

- Owns feature eligibility and leakage prevention.
- AS8 event-family predicates consume AS6-validated columns and metadata when
  available, not raw dataframe headers. Future genome inputs must preserve the
  same metadata boundary.

AS7:

- Checks setup coherence across dataset, target, and feature-set reports.
- AS8 can consume AS7 diagnostic context.
- AS8 blocks `blocked` or `error` diagnostics and may run on acceptable
  `ready` or `warning` diagnostics with warnings preserved.

## Accepted AS8 Backend MVP

Accepted implementation:

AS8 - POI Definition and Family Planner Backend.

Scope:

- Backend-only.
- Read-only.
- No persistence.
- No GUI wiring.
- No white-box discovery.
- No backtesting.
- No model training.
- No signals.

Source file:

- `src/leonardo/data/historical/analysis_suite_poi_family_planner.py`

Test file:

- `tests/test_analysis_suite_poi_family_planner.py`

Public models:

- `AnalysisSuitePoiDefinition`.
- `AnalysisSuitePoiCondition`.
- `AnalysisSuitePoiOccurrence`.
- `AnalysisSuitePoiFamilyDefinition`.
- `AnalysisSuitePoiFamilyMembership`.
- `AnalysisSuitePoiOccurrencePreviewReport`.
- `AnalysisSuitePoiFamilyPreviewReport`.
- `AnalysisSuitePoiFamilyPlanner`.

Public methods:

- `preview_poi_occurrences(...)`.
- `preview_family(...)`.
- `validate_family_definition(...)`.

Supported POI event kinds:

- `sparse_event`: occurrence where the source column has a non-null,
  non-NaN, nonzero event marker.
- `boolean_true`: occurrence where the source column is true or `1`.
- `value_equals`: occurrence where the source column equals an explicit event
  value.
- `transition`: occurrence where the previous value changes into the target
  event value.

Supported family condition operators:

- `equals`
- `not_equals`
- `gt`
- `gte`
- `lt`
- `lte`
- `in`
- `not_in`
- `is_null`
- `not_null`

Accepted behavior:

- Consume AS1 readiness or optional AS7 diagnostic context.
- Block when AS1 `can_preview == false`.
- Block blocked/error AS7 diagnostics.
- Allow non-strict but previewable datasets with warnings and blockers
  preserved.
- Use manifest/artifact metadata to validate source and condition columns
  before dataframe reads.
- Reject target-only, future-derived, and `feature_eligible = false` inputs
  when metadata is available.
- Read dataframe values only for read-only physical event and condition
  previews.
- Bound samples with default `100` and max `500`.
- Produce occurrence previews and family membership previews.
- Preserve `anchor_ts_ms`, `event_ts_ms`, and `confirmation_ts_ms` where
  knowability differs.
- Return JSON-safe reports with blockers/warnings/errors.

AS8 does not discover families automatically. It evaluates explicit POI/family
definitions. It does not treat raw CSV headers as feature or event truth.

AS8 does not compute Peaks & Troughs, UTC, or Braids. It consumes already
prepared Analysis Database columns.

## Future GUI Implications

Analysis Suite GUI work should wait until backend concepts are stable.

Future GUI audit should decide how `AnalysisSuiteWindow` or a later Analysis
Suite surface exposes:

- target preview;
- feature-set builder;
- diagnostic report;
- POI/family/category builder;
- occurrence preview;
- road/outcome summaries.

Current AS8 does not add GUI controls and does not change
`AnalysisSuiteWindow`. AnalysisSuiteWindow still exposes only the read-only
catalog and bounded dataframe preview.

## Out-Of-Scope Boundaries

AS8 does not add:

- GUI category builder.
- POI/family GUI controls.
- Persistent POI family store.
- POI definition or POI family definition persistence.
- Analysis Project/Run/Report stores.
- Road classification.
- Full outcome distribution measurement.
- Genome path building.
- Dynamic Binner implementation.
- Variation Analyzer implementation.
- White-box rule discovery.
- Backtesting engine.
- Research Suite validation integration.
- Model training.
- Neural agents.
- RL Decisor logic.
- Trading signals.
- Artifact calculation.
- Recipe execution.
- Peaks & Troughs calculation.
- UTC calculation.
- Braids calculation.
- Analysis Database build/rebuild/materialization.
- Manifest or dataframe writes.
- OHLCV repair or validation.
- Data Manager mutation.

## Proposed Patch Sequence

Recommended sequence:

1. AS8D - Docs sync.
2. AS-GUI-AUDIT - Analysis Suite GUI functionality audit.
   - Decide how to expose target preview, feature-set builder, diagnostic
     reports, and POI/family/category builder after backend concepts are
     stable.
3. AS9-AUDIT - Genome Encoding / Variation Analyzer / Dynamic Binner
   Integration.
4. AS9 - Genome Path Builder Backend.

White-box rule discovery, Research Suite validation integration, neural
refinement, and Decisor logic remain later architecture tracks.
