# Analysis Suite Design

Version: v0.4
Status: AS8 and AS9 accepted backend MVPs plus AS10-AUDIT future boundary
Date: 2026-05-30

## Purpose

This document defines the first Analysis Suite architecture for POIs, event
families, roads, outcomes, false-signal classes, genome states, and genome
paths.

AS8-AUDIT established the POI/family/road/genome design boundary. AS8
implements the first backend POI/family planner within that boundary. AS9
implements the first backend genome/path preview builder within the AS9-AUDIT
encoding boundary.

AS9 does not add GUI controls, persistence, white-box rule discovery,
backtesting, model training, signals, neural agents, Decisor logic, artifact
calculation, recipe execution, Analysis Database mutation, or OHLCV repair.

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
- AS9: `AnalysisSuiteGenomePathBuilder` builds bounded genome snapshot/path
  previews from prepared Analysis Database columns with conservative
  current/past-only encodings.

AS8 and AS9 consume AS1 readiness or optional AS7 diagnostic context. They
remain backend-only, read-only, and non-persistent.

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
5. POI / event-family occurrence preview.
6. Genome encoding and genome-path previews.
7. White-box rule discovery.
8. Research Suite validation.
9. Neural refinement.
10. Decisor selection.

AS8 is the first backend foundation for step 5. It remains limited to typed
POI/family occurrence preview.

AS9 is the first backend step for turning current and past market-state
columns into encoded genome snapshots and paths. It must not discover rules,
classify roads, train models, or generate signals.

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

A Genome is the encoded market-state vector at timestamp `t`.

The genome describes the current knowable condition of the market at that
timestamp. It is derived from AS6-eligible features, accepted OHLC/Volume
context, and prepared topology columns such as Peaks & Troughs, UTC, and
Braids. A genome may contain numeric values, symbolic bins, categorical states,
boolean markers, variation descriptors, and metadata-backed topology states.

A genome is not a prediction, trading signal, model output, or persisted model
input matrix. Later white-box and neural workflows may consume genome
representations, but AS9 only builds bounded read-only previews of those
representations.

Example fields:

- `UTC_state = bullish_transition`.
- `braid_state = compressed`.
- `T7_context = near_trough`.
- `RSI_state = recovering_low`.
- `HCK_state = bullish_shift`.
- `Bollinger_state = lower_rejection`.
- `delta_close_ema50 = negative_narrowing`.
- `variation_state = improving`.

Genome inputs must come through AS6-validated feature metadata, AS7 diagnostic
context, AS8 POI/family context, or Analysis Database manifest metadata. AS9
must not consume target outputs, future-derived labels, unknown raw CSV
headers, or feature-ineligible columns.

## Genome Component Definition

A Genome Component is one encoded field inside a genome snapshot.

Examples:

- `rsi_14_bin = lower_mid`.
- `close_ema50_delta_bin = mildly_negative`.
- `close_ema50_delta_variation = narrowing`.
- `ema_braid_state = compressed`.
- `utc_state = bullish_transition`.
- `t7_context = near_trough`.
- `volume_state = elevated`.

Required future component metadata:

- Component key and display name.
- Source column and source role.
- Source family, tool key, artifact identity, and recipe identity where
  available.
- Encoding method, such as identity numeric, categorical normalization,
  boolean symbolic, static bin, dynamic bin, or variation descriptor.
- Binning policy reference when the component is binned.
- Variation policy reference when the component describes change.
- Value type and missing-state policy.
- Leakage role, `future_derived`, and `feature_eligible` flags.
- Knowability timestamp policy for delayed topology states.
- Fitting scope and leakage status if an encoding policy was fit from data.

Components are not new dataframe columns in AS9. They are in-memory report
fields in read-only genome snapshot/path previews.

## Genome Encoding Definition

Genome encoding is the transformation from validated Analysis Database columns
into structured genome components.

Supported AS9 MVP encoding families are explicit:

- Identity numeric: preserve a numeric value as a current-row component.
- Categorical normalization: normalize string/state values into stable tokens.
- Boolean symbolic: map true/false or event markers into symbolic states.
- Static bin mapping: map numeric values through declared thresholds.
- Variation descriptor: describe current/past change state over a declared
  lookback window.

Future encoding families remain possible, but are not part of the accepted AS9
MVP:

- Dynamic bin mapping: map numeric values through a fitted or precomputed
  binning policy.
- Topology context: map prepared topology outputs into symbolic current-state
  components.

Encoding must preserve source metadata and must be deterministic for the same
input dataframe, manifest metadata, and encoding definition. AS9 implements the
conservative MVP encodings only; full Dynamic Binner and full Variation
Analyzer integration remain future work.

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
knowability. Path preview should support:

- Pre-event path: `G(t-k), ..., G(t)`.
- Post-event path: `G(t), ..., G(t+k)`.
- Event-anchored path: a path anchored to an AS8 POI occurrence or family
  membership.
- Comparison path: same-window paths for two or more POI families.

AS9 implements row-anchored pre-event path previews and optional AS8
POI/family anchoring through matched family membership samples. Post-event
paths may be represented as a later preview concept, but road classification
and outcome scoring remain out of scope.

## Variation Analyzer Role

Variation Analyzer is the layer that gives meaning to change.

It answers whether a source series is:

- expanding;
- contracting;
- accelerating;
- decelerating;
- stabilizing;
- reversing;
- converging;
- diverging;
- narrowing;
- widening;
- strengthening;
- weakening.

Example:

```text
close - EMA50 = -0.004
```

Static meaning:

```text
negative
```

Variation-aware meaning:

```text
negative but narrowing
negative and expanding
below but recovering
```

Existing financial-tool code includes `VariationAnalyzer`, which estimates a
per-series minimum meaningful movement step from time-series changes. Later
Analysis Suite genome work may integrate that capability as a policy-backed
source of variation scale or descriptors, but it must not move calculation
ownership into Analysis Suite.

Variation rules:

- Operate on current and past data only for features at timestamp `t`.
- Declare the lookback window and missing-window policy.
- Preserve source column and artifact metadata.
- Produce symbolic descriptors and/or numeric summary components.
- Reuse the same concept for deltas, slopes, angles, oscillator changes, braid
  width/compression changes, and volatility states.
- Record whether a variation policy was explicit, precomputed, or fit from a
  historical scope.
- Never inspect future rows for a component aligned to `t`.

Variation analysis belongs before white-box rule discovery. It describes
state change; it does not decide whether a rule is predictive.

## Dynamic Binner Role

Dynamic Binner is the layer that converts continuous numeric values into
symbolic bins.

Examples:

```text
RSI = 43.2 -> RSI = lower_mid_recovery_zone
delta_close_ema50 = 0.003 -> delta_close_ema50 = mildly_positive
```

Binning reduces token diversity and creates comparable condition states. The
existing financial-tool `DynamicBinner` is a deterministic signed discretizer
that consumes movement scale, and the existing `dynamic_binning` construct
orchestrates `VariationAnalyzer` plus `DynamicBinner` as a non-visual
construct. Later Analysis Suite genome work may integrate those outputs or
policies through metadata and read-only preview rules. AS9 must not calculate
artifacts or execute recipes.

Supported future bin policy families:

- Explicit/static thresholds.
- Domain-rule thresholds, such as RSI zones.
- Zero-centered signed thresholds.
- Quantile-based thresholds.
- Volatility-normalized thresholds.
- Precomputed dynamic-binning artifact outputs.

Leakage rules for binning:

- Production-safe row encoding must not fit thresholds from future rows.
- Historical exploratory policies may fit on a declared scope only when the
  report records fitting scope, data range, and leakage status.
- MVP implementation should prefer explicit/static or precomputed bin rules.
- Adaptive fitting should remain postponed until fitting-scope semantics are
  strict.

Dynamic Binner integration is a genome encoding concern, not a Data Manager
batch-generation shortcut. Current Construct Batch docs already classify
`dynamic_binning` as a grouped analysis workflow outside generic one-source
batch generation.

## Leakage And Knowability Rules

Genome components must be current/past-only at timestamp `t`.

Rules:

- Reject AS5 target outputs and labels.
- Reject `leakage_role = target_only`.
- Reject `future_derived = true`.
- Reject `feature_eligible = false`.
- Reject unknown raw CSV headers when metadata is insufficient.
- Preserve AS6 rejected/blocked candidates rather than reclassifying them.
- Treat `ts_ms` as alignment metadata, not a normal numeric genome component.
- Record source columns, source artifact identity, encoding policy, fitting
  scope, and lookback window.
- For delayed topology events, preserve both event/anchor timestamp and
  knowable timestamp. A future-confirmed event must not be represented as
  known at an earlier anchor timestamp.
- For path windows, mark early rows with insufficient lookback unavailable
  rather than filling them silently.

AS9 must not use raw CSV headers as genome truth. Physical dataframe reads are
allowed only as read-only consistency checks or value extraction after
metadata-based eligibility has accepted the source.

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

## Relationship To AS1-AS10

AS1:

- Owns dataset readiness and `can_preview`.
- AS8 blocks when AS1 says the dataset is not safely consumable.
- AS9 genome previews also block when the dataset is not safely consumable.

AS3/AS4:

- Own bounded dataframe row preview.
- AS8 should not use GUI preview as a data source.

AS5:

- Defines generic target/label preview.
- Future outcome work in this architecture is POI/event-centered and may reuse
  AS5-style formulas without becoming generic per-row labels.
- AS9 genome components must remain current/past-only and must never include
  AS5 future-dependent label outputs.

AS6:

- Owns feature eligibility and leakage prevention.
- AS8 event-family predicates consume AS6-validated columns and metadata when
  available, not raw dataframe headers. AS9 genome inputs preserve the same
  metadata boundary.
- AS9 decides how AS6-eligible selected features become genome components. It
  must not accept raw column lists that bypass AS6 eligibility diagnostics.

AS7:

- Checks setup coherence across dataset, target, and feature-set reports.
- AS8 can consume AS7 diagnostic context.
- AS8 blocks `blocked` or `error` diagnostics and may run on acceptable
  `ready` or `warning` diagnostics with warnings preserved.
- AS9 blocks `blocked` or `error` diagnostics and may run on acceptable
  `ready` or `warning` diagnostics with warnings preserved.

AS8:

- Identifies POI occurrences and POI family membership.
- AS9 can anchor genome paths around AS8 POI occurrences or matched family
  memberships.
- Pre-event genome paths support POI anticipation. Post-event genome paths may
  later support behavior and outcome analysis, but AS9 must not classify roads.

AS10:

- Future AS10 should own POI-family comparison and white-box rule discovery.
- AS9 builds encoded genome and path representations only. It must not compute
  support, precision, recall, lift, false-positive rate, or rule stability as
  discovery outputs.

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

## Accepted AS9 Backend MVP

Accepted implementation:

AS9 - Genome Path Builder Backend.

Scope:

- Backend-only.
- Read-only.
- No persistence.
- No GUI wiring.
- No white-box rule discovery.
- No backtesting.
- No model training.
- No signals.
- No artifact calculation or recipe execution.

Source file:

- `src/leonardo/data/historical/analysis_suite_genome_path_builder.py`

Test file:

- `tests/test_analysis_suite_genome_path_builder.py`

Public models:

- `AnalysisSuiteStaticBinRule`.
- `AnalysisSuiteGenomeComponentDefinition`.
- `AnalysisSuiteGenomeEncodingDefinition`.
- `AnalysisSuiteGenomeSnapshot`.
- `AnalysisSuiteGenomePath`.
- `AnalysisSuiteGenomePathPreviewReport`.
- `AnalysisSuiteGenomePathBuilder`.

Public methods:

- `validate_encoding_definition(...)`.
- `preview_paths(...)`.
- `preview_paths_for_poi_family(...)`.

Supported MVP encodings:

- `identity_numeric`: preserve numeric values as JSON-safe numbers.
- `categorical`: convert category or state values into JSON-safe string
  tokens.
- `boolean_symbolic`: map boolean or true-ish/false-ish values to `true`,
  `false`, or missing tokens.
- `static_bin`: map numeric values through explicit
  `AnalysisSuiteStaticBinRule` thresholds.
- `variation_direction`: compare the value at `t` with `t - lookback` and
  return `increasing`, `decreasing`, `flat`, or `missing`.

Accepted behavior:

- Build bounded JSON-safe genome snapshot/path previews from prepared Analysis
  Database columns.
- Support row-anchored paths ordered as `G(t-k) ... G(t)`.
- Support optional AS8 POI/family anchoring through matched family membership
  samples.
- Consume AS1 readiness, AS7 diagnostic reports, AS6 feature-set reports, and
  optional AS8 POI/family preview reports.
- Block `can_preview == false`.
- Block blocked/error AS7 diagnostics.
- Allow non-strict but previewable datasets with warnings preserved.
- Use AS6 feature-set reports or Analysis Database manifest metadata as
  semantic column truth when available.
- Block `ts_ms`, target-only, future-derived, and `feature_eligible = false`
  inputs when metadata exists.
- Read dataframe values only for read-only genome/path preview.
- Bound samples with default `100` and max `500`.
- Return bounded JSON-safe reports with blockers, warnings, and errors.
- Record source lineage, encoding policy, fitting scope, lookback window, and
  leakage/knowability metadata for every component.
- Report invalid or early anchors with structured blockers.
- Avoid raw CSV header semantic claims.

AS9 does not recompute POIs when AS8 family preview reports are supplied. AS8
owns POI occurrence discovery; AS9 owns genome/path preview construction.

Postponed behavior:

- Adaptive fitted bin policies without strict fitting-scope metadata.
- Persistent genome definitions or binner policies.
- Full Dynamic Binner implementation.
- Dynamic Binner fitting.
- Full Variation Analyzer implementation.
- Post-event road classification.
- Outcome scoring.
- Rule discovery or comparison metrics.
- GUI genome builder.

## Future GUI Implications

Analysis Suite GUI work should wait until backend concepts are stable.

Future GUI audit should decide how `AnalysisSuiteWindow` or a later Analysis
Suite surface exposes:

- target preview;
- feature-set builder;
- diagnostic report;
- POI/family/category builder;
- occurrence preview;
- genome path preview;
- road/outcome summaries.

Current AS8 and AS9 backend work does not add GUI controls and does not change
`AnalysisSuiteWindow`. AnalysisSuiteWindow still exposes only the read-only
catalog and bounded dataframe preview.

## Out-Of-Scope Boundaries

AS8 and AS9 do not add:

- GUI category builder.
- POI/family GUI controls.
- Genome builder GUI controls.
- Persistent POI family store.
- POI definition or POI family definition persistence.
- Persistent genome stores.
- Persistent binner policies.
- Analysis Project/Run/Report stores.
- Road classification.
- Full outcome distribution measurement.
- Dynamic Binner fitting.
- Full Dynamic Binner implementation.
- Full Variation Analyzer implementation.
- Automatic rule discovery.
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

1. AS9D - Docs sync for Genome Path Builder Backend.
2. AS-GUI-AUDIT - Analysis Suite GUI functionality audit.
   - Decide how to expose target preview, feature-set builder, diagnostic
     reports, POI/family/category builder, and genome path previews after
     backend contracts are stable.
3. AS10-AUDIT - POI Family Comparison and White-Box Rule Discovery
   Architecture.
   - Define comparison sets, support, precision, recall, lift,
     false-positive rate, stability, and family separation.
4. Future AS10 implementation and docs sync after AS10 architecture is
   accepted.

Research Suite validation integration, neural refinement, and Decisor logic
remain later architecture tracks.
