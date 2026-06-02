# Analysis Suite Design

Version: v0.14
Status: AS8-AS12 accepted backend MVPs and accepted AS-GUI-1/2/3 workflows
Date: 2026-05-30

## Purpose

This document defines the first Analysis Suite architecture for POIs, event
families, roads, outcomes, false-signal classes, genome states, and genome
paths.

AS8-AUDIT established the POI/family/road/genome design boundary. AS8
implements the first backend POI/family planner within that boundary. AS9
implements the first backend genome/path preview builder within the AS9-AUDIT
encoding boundary. AS-GUI-AUDIT defined the first safe Analysis Suite GUI
exposure path. AS-GUI-1 implements the accepted target, feature-set, and
diagnostic preview workflow, and AS-GUI-2 implements the accepted POI/family
preview workflow. AS-GUI-3 implements the accepted genome/path preview
workflow. AS10-AUDIT defines the first architecture for POI family comparison
and white-box rule discovery. AS10 implements the first backend-only
white-box rule testing layer within that boundary. AS11-AUDIT defines bounded
white-box rule candidate discovery and mining guardrails. AS11 implements the
first backend-only bounded single-predicate candidate scanner within that
boundary. AS12-AUDIT defines candidate validation and temporal stability
architecture for retesting AS11 candidates across chronological segments. AS12
implements the first backend-only candidate temporal validation layer within
that boundary.

AS9, AS10, AS11, AS12, AS-GUI-1, AS-GUI-2, AS-GUI-3, AS10-AUDIT,
AS11-AUDIT, and AS12-AUDIT do not add persistence, implemented broad
white-box discovery, conjunction expansion, broad candidate mining,
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
- AS-GUI-1: `AnalysisSuiteWindow` exposes AS5 target preview, AS6 feature
  candidate/selection preview, and AS7 diagnostic report preview as read-only,
  non-persistent tabs.
- AS-GUI-2: `AnalysisSuiteWindow` exposes AS8 POI occurrence preview and
  POI family membership preview as a read-only, non-persistent tab.
- AS-GUI-3: `AnalysisSuiteWindow` exposes AS9 genome encoding validation,
  row-anchored path preview, and AS8-family-anchored path preview as a
  read-only, non-persistent tab.
- AS8: `AnalysisSuitePoiFamilyPlanner` previews POI occurrences and POI
  family membership from prepared Analysis Database columns with bounded
  JSON-safe reports.
- AS9: `AnalysisSuiteGenomePathBuilder` builds bounded genome snapshot/path
  previews from prepared Analysis Database columns with conservative
  current/past-only encodings.
- AS10-AUDIT: defines POI family comparison, white-box rule candidates,
  comparison sets, road/outcome/false-signal analysis concepts, metrics, and
  guardrails for the backend-only AS10 rule-testing MVP.
- AS10: `AnalysisSuiteWhiteBoxRuleTester` tests explicit white-box rules
  against supplied AS9 genome-path comparison cohorts and reports bounded
  JSON-safe diagnostic metrics without persistence or GUI exposure.
- AS11-AUDIT: defines bounded white-box rule candidate discovery architecture,
  including predicate vocabulary, single-predicate scans, cautious conjunction
  expansion, ranking, pruning, multiple-testing warnings, temporal stability,
  family separation, and future backend MVP boundaries.
- AS11: `AnalysisSuiteRuleCandidateScanner` builds bounded single-predicate
  candidate vocabularies from supplied AS9 genome paths in AS10 comparison
  cohorts, reuses AS10 rule testing for metrics, ranks and filters candidates,
  and reports sample-limit, multiple-testing, and unknown-stability warnings
  without persistence or GUI exposure.
- AS12-AUDIT: defines candidate validation, temporal stability, chronological
  holdout discipline, rule survival, metric degradation, stability scoring,
  segment-level diagnostics, and future backend MVP boundaries.
- AS12: `AnalysisSuiteCandidateTemporalValidator` validates AS11 candidates
  across chronological discovery/validation segments, reuses AS10 rule testing
  for per-segment metrics, reports degradation, stability score, survival
  status, sample-limit context, and multiple-testing warning propagation, and
  does not persist results or expose GUI controls.

AS8 and AS9 consume AS1 readiness or optional AS7 diagnostic context. AS10 can
consume optional AS7 diagnostic context and supplied AS9 path reports. AS11
consumes AS10 comparison sets and supplied AS9 path components. AS12 consumes
AS10 comparison sets and AS11 candidate scan reports. These backend services
remain read-only and non-persistent. AS-GUI-2 exposes AS8 reports in the GUI
without moving AS8 policy, dataframe reads, or persistence into the GUI.
AS-GUI-3 exposes AS9 reports in the GUI without moving AS9 policy, dataframe
reads, genome encoding, path construction, or persistence into the GUI. AS10,
AS11, and AS12 validation controls are not exposed in the GUI yet.

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

AS10-AUDIT is the first architecture step for comparing POI families and
evaluating explainable rule candidates. It defines the boundary for future
white-box diagnostics without implementing the backend, GUI, persistence,
signals, backtesting, model training, or trading execution.

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

## Relationship To AS1-AS12

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

- AS10 owns explicit white-box rule testing over supplied comparison cohorts
  and AS9 genome paths.
- AS9 builds encoded genome and path representations only. It must not compute
  support, precision, recall, lift, false-positive rate, or rule stability as
  rule-testing outputs.

AS11:

- AS11-AUDIT owns bounded candidate discovery architecture and mining
  guardrails.
- AS11 owns bounded single-predicate candidate vocabulary generation and scan
  orchestration.
- AS11 reuses AS10 metrics rather than duplicating rule-test evaluation.

AS12:

- AS12-AUDIT owns candidate validation and temporal stability architecture.
- AS12 consumes AS11 candidates and AS10 comparison sets, splits cohorts by
  known anchor timestamps, and reuses AS10 rule testing for per-segment
  metrics.
- AS12 must not re-scan candidates, rebuild AS9 genome paths, recompute AS8
  POIs, or duplicate AS10 metric formulas unless a later backend patch
  explicitly extends those contracts.

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

## AS-GUI-AUDIT - Analysis Suite GUI Functionality Audit

AS-GUI-AUDIT was the design-only boundary for exposing accepted backend
planners in `AnalysisSuiteWindow`. It did not add widgets, dialogs, actions,
service wiring, persistence, stores, or runtime behavior.

Pre-AS-GUI-1 `AnalysisSuiteWindow` baseline found by the audit:

- Opens from `Analysis -> Analysis Suite` through `WindowManager`.
- Displays the AS1 readiness catalog in a read-only table.
- Shows selected readiness details, blockers, warnings, errors, source drift,
  and topology/geography state.
- Provides bounded Head/Tail dataframe preview through
  `AnalysisSuiteDataframePreviewService`.
- Enables preview only when the selected AS1 report has `can_preview == True`.
- Routes preparation work back to Data Manager through `Open Data Manager`.
- Offers `Refresh Catalog` and `Close`.
- Constructs AS1/AS3 backend services from the configured historical root, with
  test-injected service protocols available.
- Did not load `dataframe.csv` directly, inspect manifests for policy, call
  `AnalysisDatabaseStore.load_dataframe(...)`, mutate Data Manager objects, or
  call AS5-AS9 services before AS-GUI-1.

Backend services reviewed for GUI exposure:

- AS5 `AnalysisSuiteTargetPlanner` is safe for read-only target preview
  controls. The GUI collects target family, horizon, and thresholds, then
  displays `AnalysisSuiteTargetPreviewReport` fields. The GUI must not persist
  target definitions or labels, and must not calculate labels itself.
- AS6 `AnalysisSuiteFeatureSetPlanner` is safe for read-only candidate and
  feature-selection preview after a selected database and target context exist.
  The GUI collects selected columns from service-produced candidates, then
  displays accepted/rejected features, group summaries, leakage summaries,
  blockers, warnings, and errors. The GUI must not infer eligibility from raw
  CSV headers or duplicate leakage policy.
- AS7 `AnalysisSuiteDiagnosticReportService` is safe for read-only diagnostic
  preview once AS1, AS5, and AS6 reports are available. The GUI displays final
  status, label availability, target statistics or class distribution, feature
  missingness/dtype diagnostics, leakage blockers, and combined
  blockers/warnings/errors. The GUI must not write reports or create project,
  run, or report stores.
- AS8 `AnalysisSuitePoiFamilyPlanner` is exposed through AS-GUI-2 after the
  target, feature, and diagnostic setup workflow became stable enough for the
  first POI/family preview surface.
- AS9 `AnalysisSuiteGenomePathBuilder` is exposed through AS-GUI-3 after AS8
  POI/family GUI concepts became available. It remains read-only and
  non-persistent; backend services still own encoding validation, dataframe
  reads, path construction, and POI-family anchoring semantics.

## Accepted AS-GUI-1 - Target / Feature / Diagnostic Preview UI

AS-GUI-1 implements the first interactive Analysis Suite setup workflow in
`AnalysisSuiteWindow`. It preserves the AS1 readiness catalog, selected
readiness details, AS3 bounded dataframe preview behavior, `Open Data Manager`
routing, `Refresh Catalog`, and `Close`.

The accepted tab area contains:

- `Data Preview`: existing AS3 bounded Head/Tail dataframe preview.
- `Target Preview`: AS5 target preview controls and report rendering.
- `Feature Set`: AS6 feature candidate listing, selected-feature validation,
  and report rendering.
- `Diagnostic Report`: AS7 diagnostic report rendering from current AS1, AS5,
  and AS6 report objects.

The `Target Preview` tab lets the user configure:

- target family: future return regression or future direction classification;
- `horizon_bars`;
- up/down thresholds for direction classification.

It calls `AnalysisSuiteTargetPlanner` and displays label availability, target
statistics or class distribution, leakage metadata, blockers, warnings, and
errors. Target definitions remain in memory and are not persisted.

The `Feature Set` tab lists AS6 feature candidates, including status, group,
reason, and source metadata where available. The user may select candidate
features for validation, use `Select All Eligible`, clear selection, and
preview the feature set. `Select All Eligible` selects only candidates reported
as eligible by the backend. The tab calls `AnalysisSuiteFeatureSetPlanner` and
displays selected/rejected features, group summaries, leakage summaries,
blockers, warnings, and errors. Feature sets remain in memory and are not
persisted.

The `Diagnostic Report` tab requires a selected database, a current target
preview, and a current feature-set preview. It calls
`AnalysisSuiteDiagnosticReportService` and displays final `ready`, `warning`,
`blocked`, or `error` status with dataset, target, feature, leakage, label,
missingness, dtype, blocker, warning, and error diagnostics. Diagnostic reports
remain in memory and are not persisted.

AS-GUI-1 clears stale state:

- selecting a different Analysis Database clears target, feature, and
  diagnostic previews;
- changing target settings clears downstream feature and diagnostic state;
- changing feature selection clears diagnostic state.

Backend services remain the policy owners. The GUI collects intent and renders
reports, while AS5/AS6/AS7 own target generation, feature eligibility, leakage
checks, dataframe reads, diagnostic composition, missingness/dtype checks,
blockers, warnings, and errors. The GUI does not read `dataframe.csv` directly,
parse `manifest.json` directly for readiness/feature/leakage policy, infer raw
CSV header feature truth, or duplicate backend leakage policy.

Manual GUI exploration after AS-GUI-1 found the workflow acceptable for
continued work. Layout and small usability polish remain future work; the
workflow UX is not treated as final.

Recommended staging:

1. AS-GUI-1D - Target / Feature / Diagnostic Preview UI docs sync.
   - Document accepted AS-GUI-1 behavior and manual smoke-check status.
2. AS-GUI-2 - POI / Family Preview UI.
   - Implemented as the accepted AS8 GUI preview workflow.
3. AS-GUI-2D - POI / Family Preview UI docs sync.
   - Document accepted AS-GUI-2 behavior and preserve no-persistence/no-mutation
     boundaries.
4. AS-GUI-3 - Genome Path Preview UI.
   - Implemented as the accepted AS9 genome/path preview workflow.
5. AS-GUI-3D - Genome Path Preview UI docs sync.
   - Document accepted AS-GUI-3 behavior and preserve no-persistence/no-mutation
     boundaries.
6. AS10-AUDIT - POI Family Comparison and White-Box Rule Discovery
   Architecture.
   - Define comparison metrics and rule-discovery boundaries after the GUI can
     inspect current backend setup objects.

Suggested layout direction:

- Preserve the current read-only catalog as the left-side selection anchor.
- Keep readiness details and bounded dataframe preview available.
- Use the accepted tabbed setup area for `Data Preview`, `Target Preview`,
  `Feature Set`, `Diagnostic Report`, `POI / Family Preview`, and
  `Genome Path Preview`.
- Reset target, feature, diagnostic, POI, and family preview state when the
  selected database changes.
- Reset genome preview state when the selected database, feature/diagnostic,
  POI/family, or encoding context changes.

Service orchestration boundary:

- GUI code calls backend services through narrow GUI-owned orchestration
  methods and injected service protocols, matching the AS1/AS3 testable
  pattern.
- New CoreBridge APIs were not added by AS-GUI-1. A later lifecycle audit may
  revisit centralized service registration if needed.
- GUI code may collect user intent and render report objects, but backend
  services must own target generation, feature eligibility, leakage policy,
  diagnostic coherence, POI occurrence detection, family membership matching,
  source/condition validation, genome component validation, genome encoding,
  path construction, dataframe reads, and JSON-safe report construction.
- GUI code must not duplicate Data Manager persistence, Analysis Database
  materialization, artifact calculation, recipe execution, or OHLCV repair
  ownership.

AS-GUI-1 test coverage requirements:

- `AnalysisSuiteWindow` exposes target preview controls only after a database
  selection.
- Target preview calls `AnalysisSuiteTargetPlanner`; the GUI does not compute
  labels or read dataframe values directly.
- Feature candidate and selection preview calls `AnalysisSuiteFeatureSetPlanner`
  and preserves backend ordering, blockers, warnings, errors, and leakage
  diagnostics.
- Diagnostic preview calls `AnalysisSuiteDiagnosticReportService` using the
  AS1, AS5, and AS6 report objects.
- Stale target, feature, and diagnostic previews clear when the selected
  database changes or the catalog refreshes.
- Existing AS1 readiness catalog and AS3 bounded dataframe preview behavior
  remains covered.
- Static boundary tests confirm no Analysis Database build/rebuild/materialize
  calls, manifest/dataframe writes, Data Manager mutation, stores, model
  training, signal generation, backtesting, or GUI-owned leakage policy.

AS-GUI-1 does not add:

- Persistence for targets, labels, feature sets, diagnostic reports, POI
  definitions, POI families, genome definitions, or genome paths.
- Analysis Project/Run/Report stores.
- AS8 POI/family controls.
- AS9 genome/path controls.
- Category-builder UI.
- White-box rule discovery, rule mining, backtesting, road classification,
  model training, signals, or trading logic.
- Artifact calculation, recipe execution, database build/rebuild/materialize
  operations, component editing, OHLCV repair/validation, manifest writes, or
  dataframe writes.

## Accepted AS-GUI-2 - POI / Family Preview UI

AS-GUI-2 implements the first AS8 POI/family GUI workflow in
`AnalysisSuiteWindow`. It preserves the AS1 readiness catalog, AS3 bounded
dataframe preview behavior, AS5 target preview, AS6 feature-set preview, AS7
diagnostic report preview, `Open Data Manager` routing, `Refresh Catalog`, and
`Close`.

The accepted tab area now contains:

- `Data Preview`: existing AS3 bounded Head/Tail dataframe preview.
- `Target Preview`: AS5 target preview controls and report rendering.
- `Feature Set`: AS6 feature candidate listing, selected-feature validation,
  and report rendering.
- `Diagnostic Report`: AS7 diagnostic report rendering from current AS1, AS5,
  and AS6 report objects.
- `POI / Family Preview`: AS8 POI occurrence and family membership preview.

The `POI / Family Preview` tab has a POI Definition section. It lets the user
enter POI key, display name, POI type, source column, event kind, event value,
and previous value. It exposes AS8 event kinds `sparse_event`,
`boolean_true`, `value_equals`, and `transition`. The tab builds an in-memory
`AnalysisSuitePoiDefinition`, calls
`AnalysisSuitePoiFamilyPlanner.preview_poi_occurrences(...)`, and displays
status, row count, occurrence count, first/last occurrence timestamps when
available, sample occurrences, blockers, warnings, and errors. POI definitions
are not persisted.

The same tab has a Family Conditions section. It lets the user enter family
key/name and condition rows with column, operator, value, values,
`lookback_bars`, required flag, and label. Conditions remain simple AND-style
MVP rules. Supported AS8 operators are `equals`, `not_equals`, `gt`, `gte`,
`lt`, `lte`, `in`, `not_in`, `is_null`, and `not_null`. The tab builds an
in-memory `AnalysisSuitePoiFamilyDefinition`, calls
`AnalysisSuitePoiFamilyPlanner.preview_family(...)`, and displays status,
occurrence count, matched count, unmatched count, sample memberships,
condition result summaries, blockers, warnings, and errors. POI family
definitions are not persisted.

AS-GUI-2 clears stale state:

- selecting a different Analysis Database clears POI and family reports;
- feature or diagnostic changes clear stale POI/family reports;
- changing POI definition inputs clears stale occurrence and family reports;
- changing family condition inputs clears stale family reports.

Backend services remain the policy owners. The GUI collects POI/family intent
and renders AS8 report objects, while AS8 owns dataframe reads, POI occurrence
detection, family membership matching, source/condition validation, leakage
checks, blockers, warnings, errors, and JSON-safe report construction. The GUI
does not read `dataframe.csv` directly, parse `manifest.json` directly for
readiness/feature/leakage/POI policy, compute POI occurrences, compute family
memberships, infer raw CSV header event truth, or duplicate backend leakage or
source-eligibility policy.

AS-GUI-2 does not add:

- AS9 genome/path controls or genome encoding controls.
- Category-builder UI.
- Persistence for POI definitions, POI families, targets, labels, feature
  sets, diagnostic reports, genome definitions, or genome paths.
- POI/family stores, genome stores, or Analysis Project/Run/Report stores.
- White-box rule discovery, rule mining, backtesting, road classification,
  outcome distribution analysis, model training, signals, or trading logic.
- Artifact calculation, recipe execution, database build/rebuild/materialize
  operations, component editing, OHLCV repair/validation, manifest writes, or
  dataframe writes.

Recommended staging after AS-GUI-2:

1. AS-GUI-2D - POI / Family Preview UI docs sync.
   - Document accepted AS-GUI-2 behavior and preserve backend-owned policy and
     no-persistence/no-mutation boundaries.
2. AS-GUI-3 - Genome Path Preview UI.
   - Implemented as the accepted AS9 genome/path preview workflow.
3. AS-GUI-3D - Genome Path Preview UI docs sync.
   - Document accepted AS-GUI-3 behavior and preserve backend-owned policy and
     no-persistence/no-mutation boundaries.
4. AS10-AUDIT - POI Family Comparison and White-Box Rule Discovery
   Architecture.
   - Define comparison sets, support, precision, recall, lift,
     false-positive rate, stability, and family separation.

## Accepted AS-GUI-3 - Genome Path Preview UI

AS-GUI-3 implements the first AS9 genome/path GUI workflow in
`AnalysisSuiteWindow`. It preserves the AS1 readiness catalog, AS3 bounded
dataframe preview behavior, AS5 target preview, AS6 feature-set preview, AS7
diagnostic report preview, AS8 POI/family preview, `Open Data Manager`
routing, `Refresh Catalog`, and `Close`.

The accepted tab area now contains:

- `Data Preview`: existing AS3 bounded Head/Tail dataframe preview.
- `Target Preview`: AS5 target preview controls and report rendering.
- `Feature Set`: AS6 feature candidate listing, selected-feature validation,
  and report rendering.
- `Diagnostic Report`: AS7 diagnostic report rendering from current AS1, AS5,
  and AS6 report objects.
- `POI / Family Preview`: AS8 POI occurrence and family membership preview.
- `Genome Path Preview`: AS9 genome encoding validation and genome path
  preview.

The `Genome Path Preview` tab has an Encoding Definition section. It lets the
user enter encoding key, display name, `path_length_bars`, anchor mode, and
component rows. Component rows include enabled state, component key, source
column, encoding type, static bin config where used, `lookback_bars`, missing
token, and display name. Supported AS9 encodings are `identity_numeric`,
`categorical`, `boolean_symbolic`, `static_bin`, and `variation_direction`.
The tab builds an in-memory `AnalysisSuiteGenomeEncodingDefinition`, calls
`AnalysisSuiteGenomePathBuilder.validate_encoding_definition(...)`, and
displays validation blockers, warnings, and errors. Genome encoding
definitions are not persisted.

Row-anchored path preview calls
`AnalysisSuiteGenomePathBuilder.preview_paths(...)` and displays status, row
count, path count, sample paths, sample snapshots/components, blockers,
warnings, and errors. POI-family-anchored path preview requires a current AS8
family preview report, calls
`AnalysisSuiteGenomePathBuilder.preview_paths_for_poi_family(...)`, and uses
the same bounded report style. AS8 owns POI/family discovery, AS9 owns
genome/path preview construction, and the GUI does not recompute POIs or
persist genome paths.

AS-GUI-3 exposes only AS9 MVP encodings:

- `identity_numeric`: keeps numeric values as JSON-safe numbers.
- `categorical`: converts categorical/state values into JSON-safe tokens.
- `boolean_symbolic`: converts boolean or true-ish/false-ish values into
  symbolic tokens.
- `static_bin`: uses explicit static bin rules only, with no quantile learning,
  adaptive threshold fitting, or Dynamic Binner fitting.
- `variation_direction`: uses only `t` and `t - lookback` for conservative
  direction descriptors. It is not the full Variation Analyzer engine.

AS-GUI-3 clears stale state:

- selecting a different Analysis Database clears genome validation and path
  reports;
- feature, diagnostic, POI, or family changes clear stale genome reports;
- changing encoding definition or component inputs clears stale genome path
  reports.

Backend services remain the policy owners. The GUI collects genome/path intent
and renders AS9 report objects, while AS9 owns dataframe reads, component
source validation, leakage/source eligibility checks, encoding values,
variation descriptors, static bin application, path construction,
POI-family anchoring interpretation, blockers, warnings, errors, and
JSON-safe report construction. The GUI does not read `dataframe.csv` directly,
parse `manifest.json` directly for readiness/feature/leakage/POI/genome
policy, compute genome snapshots, compute genome paths, compute variation
descriptors, fit bins, infer raw CSV header genome truth, or duplicate AS9
source/encoding validation policy.

AS-GUI-3 does not add:

- AS10 controls.
- White-box rule discovery or rule mining.
- Category-builder UI.
- Persistence for genome definitions, genome encoding definitions, genome
  paths, targets, labels, feature sets, diagnostic reports, POI definitions,
  or POI families.
- Genome stores, POI/family stores, or Analysis Project/Run/Report stores.
- Dynamic Binner fitting, full Dynamic Binner, or full Variation Analyzer.
- Backtesting, road classification, outcome distribution analysis, model
  training, signals, or trading logic.
- Artifact calculation, recipe execution, database build/rebuild/materialize
  operations, component editing, OHLCV repair/validation, manifest writes, or
  dataframe writes.

Recommended staging after AS-GUI-3:

1. AS-GUI-3D - Genome Path Preview UI docs sync.
   - Document accepted AS-GUI-3 behavior and preserve backend-owned policy and
     no-persistence/no-mutation boundaries.
2. AS10-AUDIT - POI Family Comparison and White-Box Rule Discovery
   Architecture.
   - Implemented by this design section as the white-box comparison
     architecture boundary.
3. AS10 - White-Box Rule Testing Backend.
   - Implemented backend-only, read-only rule-testing MVP.
4. AS10D - Docs sync.
   - Document accepted AS10 backend behavior and preserve no-GUI,
     no-persistence, no-discovery, and no-mutation boundaries.
5. AS11-AUDIT - White-Box Rule Discovery / Candidate Mining Architecture.
   - Implemented by this design section as the bounded candidate-discovery
     architecture boundary.
6. Optional GUI polish audit if manual AS-GUI-3 exploration finds usability
   issues.

## AS10-AUDIT - POI Family Comparison And White-Box Rule Discovery Architecture

AS10-AUDIT defined the first white-box analysis architecture after the
accepted AS1-AS9 and AS-GUI-1/2/3 foundation. AS8 identifies POI/family
occurrences. AS9 builds genome snapshots and paths around rows or matched
POI/family anchors. AS10 now implements the first backend service for
comparing supplied cohorts and evaluating explicit, human-readable rules.

AS10 remains backend-only and read-only. It does not add GUI controls,
persistence, stores, model training, signal generation, backtesting, PnL
validation, order generation, trading execution, neural agents, RL Decisor
logic, artifact calculation, recipe execution, Analysis Database mutation, or
OHLCV repair.

### White-Box Rule

A white-box rule is an explicit, human-readable condition or conjunction of
conditions over AS9 genome components and AS8 POI/family context. Examples:

- `rsi_14_bin in {low, lower_mid}` AND `braid_width_variation = narrowing`.
- `utc_state = bullish_transition` AND
  `close_ema50_delta_variation = improving`.
- `t7_trough` AND `volume_state = elevated` AND
  `prior_3_path = compression_release`.

A rule is not a model, trading signal, persisted strategy, or order policy.
It is an explainable candidate relationship between current/past-known
conditions and a future outcome, road, false-signal class, or POI family
membership label.

### Rule Candidate

A rule candidate is a rule under test before acceptance. AS10 represents tested
explicit rules and their diagnostics. AS11 now represents proposed
single-predicate candidates and adds enough context to audit what was proposed,
tested, filtered, ranked, and why it passed or failed. Conceptual fields:

- `rule_key`.
- predicates or components used by the rule.
- anchor type such as row, POI occurrence, POI family membership, or genome
  path anchor.
- family scope or comparison-set scope.
- target outcome, road, false-signal class, or family-membership objective.
- support counts.
- precision, recall, lift, false-positive count, and false-negative count.
- time stability and split-survival diagnostics.
- blockers, warnings, and errors.

Rule candidates remain diagnostics until a later validation layer accepts or
rejects them. Candidate ranking must keep support and time stability visible
so rare rules are not mistaken for robust findings.

### Comparison Set

A comparison set defines the cohorts used to measure a rule. It must identify
positive examples, negative or background examples, inclusion rules, exclusion
rules, anchor logic, sample counts, time range, and leakage constraints.

Common comparison-set patterns:

- family A vs all other POI events.
- family A success vs family A failure.
- family A road X vs family A road Y.
- true POI vs false signal.
- pre-event windows for matched events vs random or non-event windows.
- family A vs family B.

The positive cohort defines what the rule is trying to identify. The negative
or background cohort defines what it must separate from. AS10 must not mix
future-derived outcomes into predicates, and it must not let outcome labels
become AS9 genome components.

### Roads, Outcomes, And False-Signal Classes

A road is an event-centered analysis class describing what path followed a
POI or family occurrence. AS10 may define road labels such as
`continuation_up`, `continuation_down`, `failed_breakout`, `reversal`,
`range_continuation`, `exhaustion`, or `no_follow_through`.

Road classification is not a trading signal. Roads describe observed or
defined post-event behavior for analysis. A later backend may derive roads
from explicit outcome definitions, but AS10-AUDIT does not implement road
classification.

Outcome definitions describe future-dependent facts that support road labels
or rule evaluation. Examples:

- future return over N bars.
- max favorable excursion.
- max adverse excursion.
- time to threshold.
- failure-before-target.
- direction class.
- volatility expansion or contraction.
- drawdown after POI.
- duration until invalidation.

Outcome definitions are target-like. They are future-derived and must be
marked as target/output-only, not feature-eligible. Outcome computation
belongs to a future backend implementation, not AS10-AUDIT.

A false-signal class describes structured failure after a POI or family
occurrence. Examples include no movement after a POI, movement that starts and
then reverses, failed breakout, trough becoming continuation down, peak
becoming continuation up, topology contradiction, or road expectation failure
before threshold. False-signal classes are valid comparison-set objectives,
especially for true-vs-false and success-vs-failure cohorts.

### Metrics And Guardrails

AS10 metrics are diagnostic, not trading performance. They must not be
presented as proof of profitability. Profit/loss validation belongs to later
Research Suite validation or backtesting architecture.

Required conceptual metrics:

- support: matched positive count and total matched count.
- coverage: fraction of the eligible cohort matched by the rule.
- precision: matched positives divided by total matches.
- recall: matched positives divided by total positives.
- lift: rule precision divided by baseline positive rate.
- false-positive rate: false positives divided by all negatives.
- false-negative rate: false negatives divided by all positives.
- specificity: true negatives divided by all negatives.
- balanced precision/recall summary such as F1 or an explicit balanced score.
- family separation: how strongly the rule distinguishes one family, road, or
  outcome cohort from another.
- class imbalance warnings.
- rule rarity warnings.
- time stability and split survival.
- temporal degradation between older and newer data.
- confidence intervals as future scope when sample size supports them.

Support must be reported alongside precision and lift. Support should include
positive matches, total matches, support by family/outcome, and support by
time split. Minimum support thresholds must run before ranking. A rule with
high precision but very low support must be flagged as rare rather than
treated as reliable.

Lift compares rule precision to the baseline positive rate. If the baseline
positive road rate is 20% and a rule matches positives 45% of the time, lift
is 2.25. High lift with tiny support is suspicious and must be reported with
support and stability diagnostics.

Stability must be evaluated across chronological splits at minimum. Future
extensions may add market regime, symbol/timeframe, recent-vs-old, and
volatility-segment diagnostics. Rules that work only in one short period
should receive stability warnings even if aggregate precision is high.

### Rule Testing Versus Rule Discovery

Rule testing means the user or caller supplies explicit predicates, and AS10
reports metrics against a comparison set. Rule discovery means AS11 or later
services propose candidate predicates from a bounded search.

The accepted AS10 MVP starts with explicit rule testing only. It does not
perform single-predicate candidate scans or broader candidate mining.
AS11 now implements bounded single-predicate candidate scans. Broader
discovery should wait for later audit because unconstrained conjunction search
can overfit quickly. Future candidate generation should use minimum support
first, small conjunction limits, explicit predicate vocabulary from
AS9 genome components and AS8 family context, temporal split validation, and
bounded output.

Future white-box discovery is not model training, neural refinement, RL Decisor
logic, signal generation, or trading execution.

### Relationship To AS5, AS7, AS8, And AS9

AS5 target labels are generic future labels. AS10 outcomes and roads may reuse
AS5-style future-return or direction logic, but AS10 labels are event-centered
and comparison-set-aware. Future-dependent AS10 outcome outputs must never
become AS9 genome components.

AS7 remains the setup coherence checkpoint. AS10 accepts an AS7 diagnostic
report when available and blocks or warns according to the established `ready`,
`warning`, `blocked`, and `error` diagnostic status pattern.

AS8 owns POI occurrence and family membership discovery. AS10 consumes AS8
reports to build comparison cohorts and should not recompute POIs when AS8
reports are supplied.

AS9 owns genome component encoding and genome path preview construction. AS10
consumes AS9 genome/path components as predicate vocabulary and should not
re-encode genome paths when AS9 reports are supplied.

### Accepted AS10 Backend Behavior

AS10 implements `AnalysisSuiteWhiteBoxRuleTester` as the first conservative
white-box rule testing backend. It is backend-only, read-only, non-persistent,
and has no GUI exposure. It evaluates caller-supplied
`AnalysisSuiteWhiteBoxRuleDefinition` objects against explicit
`AnalysisSuiteComparisonSetDefinition` positive and negative/background cohorts
containing AS9 genome paths or JSON-like AS9 path dictionaries.

Accepted AS10 data contracts:

- `AnalysisSuiteRulePredicate`.
- `AnalysisSuiteWhiteBoxRuleDefinition`.
- `AnalysisSuiteComparisonCohort`.
- `AnalysisSuiteComparisonSetDefinition`.
- `AnalysisSuitePredicateResult`.
- `AnalysisSuiteRuleMatch`.
- `AnalysisSuiteRuleMetricSummary`.
- `AnalysisSuiteRuleValidationReport`.
- `AnalysisSuiteRuleTestReport`.
- `AnalysisSuiteWhiteBoxRuleTester`.

Accepted AS10 public methods:

- `validate_rule_definition(...)`.
- `test_rule(...)`.
- `build_comparison_set_from_path_reports(...)`.

AS10 predicates support `equals`, `not_equals`, `gt`, `gte`, `lt`, `lte`,
`in`, `not_in`, `is_null`, and `not_null`. MVP rules use AND semantics only.
There are no nested expression trees, OR groups, arbitrary expression
evaluation, executable predicates, regex policies, or `eval`.

Predicate `path_offset` selects the AS9 genome snapshot to inspect:

- `0` means the anchor snapshot `G(t)`.
- negative offsets select previous snapshots such as `G(t-1)`.
- positive offsets are blocked to prevent future-snapshot leakage.

Missing required components fail the predicate and produce structured
predicate result details. Optional missing predicates may warn without causing
the rule match to fail.

AS10 comparison sets are explicit. The tester does not silently invent
negative examples, does not recompute AS8 POIs or family membership, and does
not rebuild AS9 genome paths when path reports are supplied. Empty rules and
empty cohorts block. Cohort identity overlap and missing time-split metadata
are surfaced as diagnostics when detected.

AS10 reports these diagnostic metrics:

- true positives.
- false positives.
- false negatives.
- true negatives.
- support.
- coverage.
- precision.
- recall.
- specificity.
- false-positive rate.
- false-negative rate.
- baseline positive rate.
- matched positive rate.
- lift.

Support is the total number of matched examples across the evaluated positive
and negative/background cohorts. Metrics handle zero denominators safely and
warn on small total, positive, negative, or matched support samples. Metrics
are evidence-quality diagnostics, not trading performance, profit validation,
or backtest results.

AS10 preserves AS7 diagnostic gating: blocked/error diagnostic reports block
rule testing, warning diagnostics allow testing with warning, and ready
diagnostics allow testing. When comparison cohorts are built from bounded AS9
path previews, AS10 reports `evaluated_sample_limited`, `input_path_count`,
`evaluated_path_count`, requested sample limit, and effective sample limit so
preview metrics are not mistaken for full-cohort claims.

AS10 does not implement broad rule discovery, candidate scanning, conjunction
mining, rule stores, GUI controls, persistence, model training, signal
generation, backtesting, PnL/profit validation, order generation, trading
execution, neural agents, RL Decisor logic, artifact calculation, recipe
execution, Analysis Database mutation, OHLCV repair, Data Manager mutation,
direct `dataframe.csv` reads, or direct `manifest.json` policy parsing.

AS11 now owns bounded single-predicate candidate scanning. Broader candidate
discovery, conjunction expansion, and temporal validation remain later
architecture and implementation scope.

### Future GUI Implications

AS10 has no GUI exposure. A future GUI should expose rule testing only after
manual/backend review confirms the AS10 report contract is stable enough for
interactive use. The GUI should collect comparison-set and rule intent, render
backend reports, and preserve the established Analysis Suite rule that policy,
dataframe reads, metrics, and blockers belong to backend services. The GUI
must not compute rule metrics, infer feature truth from raw CSV headers,
persist rules, create stores, produce signals, or run backtests.

### Proposed Patch Sequence After AS10-AUDIT

Recommended sequence:

1. AS10D - Docs sync.
   - Document accepted AS10 backend behavior after implementation.
2. AS11-AUDIT - White-Box Rule Discovery / Candidate Mining Architecture.
   - Define bounded candidate generation, overfitting guardrails, rule
     ranking, rule pruning, temporal split validation, and false-discovery
     controls.

## AS11-AUDIT - White-Box Rule Candidate Discovery / Bounded Mining Architecture

AS11-AUDIT defines the architecture for proposing white-box rule candidates
after AS10 has established explicit rule testing. It is design-only. It does
not implement a backend service, GUI controls, persistence, stores, model
training, signal generation, backtesting, PnL validation, order generation,
trading execution, neural agents, RL Decisor logic, artifact calculation,
recipe execution, Analysis Database mutation, OHLCV repair, or Data Manager
mutation.

The AS11 question is constrained: given AS8 POI/family occurrence context, AS9
genome paths, and AS10 comparison sets plus rule metrics, Leonardo may propose
candidate rules that separate positive and negative cohorts. The proposal is a
diagnostic starting point, not a validated strategy or signal.

### Rule Candidate Discovery

Rule candidate discovery is bounded diagnostic generation of candidate
white-box rules from a controlled predicate vocabulary. Discovery proposes
candidate relationships. It does not validate profitability, create trading
signals, persist strategies, or accept rules without diagnostics.

Every candidate report must preserve the AS10 evidence contract: support,
precision, recall, lift, false positives, false negatives, warnings, blockers,
and sample-limit context must remain visible. Candidate discovery must never
present a ranked candidate without enough information to explain why it was
returned and what guardrails it failed or passed.

### Predicate Vocabulary

The predicate vocabulary is the finite set of possible AS10 predicates derived
from supplied AS9 genome paths and component metadata. The vocabulary should
prefer semantic, bounded components over raw numeric threshold proliferation.
Examples:

- symbolic component equals a token;
- symbolic component is in a small explicit token set;
- categorical component equals a value observed in the supplied paths;
- static-bin component equals a bin label;
- variation-direction component equals `increasing`, `decreasing`, `flat`, or
  `missing`;
- numeric component greater than, greater than or equal to, less than, or less
  than or equal to a small explicit static threshold set, when thresholds are
  supplied by configuration or AS9 metadata.

The vocabulary must be bounded before evaluation begins. It must not include
arbitrary expressions, executable code, regex-as-rule policies, free-form
Python, positive path offsets, or future-derived components. Predicate
`path_offset` remains `0` for the anchor snapshot or negative for previous
snapshots. Positive offsets are blocked by AS10 and must not be generated by
AS11.

### Single-Predicate Scan

The first discovery layer should scan one predicate at a time:

1. Build a bounded predicate vocabulary from supplied AS9 paths and explicit
   configuration.
2. Convert each predicate into an AS10 `AnalysisSuiteWhiteBoxRuleDefinition`
   with one predicate.
3. Evaluate each rule through `AnalysisSuiteWhiteBoxRuleTester`.
4. Filter candidates below minimum support and required guardrails.
5. Rank the remaining candidates with support-first diagnostic scoring.
6. Return bounded JSON-safe candidate summaries and AS10 metric summaries.

This is the accepted AS11 backend MVP shape. The implementation reuses AS10
for metrics and avoids introducing a second owner for rule evaluation.

### Conjunction Expansion

Conjunction expansion is a later, cautious extension that combines a small
number of already-strong single predicates. MVP expansion should be postponed
unless implementation can keep it narrowly bounded. If included later, the
default maximum conjunction size should be `2`; size `3` should remain future
scope until pruning, split validation, and false-discovery controls are proven.

Expansion rules:

- start only from top single-predicate candidates that pass support thresholds;
- combine only predicates that use compatible offsets and non-duplicated
  component/operator/value identities;
- require support not to collapse below configured thresholds;
- require precision or lift improvement over each parent predicate;
- prune conjunctions that are redundant, dominated by simpler rules, or
  unstable across time splits;
- avoid full itemset explosion, unrestricted Cartesian products, deep search
  trees, genetic programming, or adaptive expression synthesis.

### Candidate Ranking Metrics

Candidate ranking must prioritize evidence quality before headline metrics.
Recommended ordering:

1. Minimum support and cohort-size guardrails.
2. Precision and lift.
3. Recall and coverage.
4. False-positive rate.
5. Stability score when split validation is available.
6. Simplicity and explainability.
7. Penalties or warnings for sample-limited input and large candidate scans.

A useful score may include `support_count`, precision, lift, recall,
false-positive rate, stability score, a simplicity penalty, sample-limit
warnings, and multiple-testing warnings. The score is diagnostic only. High
lift with tiny support should rank lower or be flagged. High precision with
tiny recall should be flagged. No score should be described as profitability
or trading quality.

### Candidate Pruning

AS11 candidate pruning removes or blocks MVP candidates for:

- candidates below configured minimum support;
- candidates below configured minimum positive matches;
- candidates below configured precision or lift thresholds when those
  thresholds are supplied;
- predicates using blocked, leaky, target-only, or future-derived components;
- predicates with positive path offsets;
- candidates built from sample-limited data without explicit warnings.

Duplicate-candidate pruning, false-positive thresholds, conjunction parent
improvement checks, and stability-based pruning remain future work.

Pruning decisions must be reported with candidate counts and reasons:
`candidate_count_scanned`, `candidate_count_filtered`,
`candidate_count_returned`, and filter summaries are part of the AS11 report
contract.

### Multiple-Testing And False Discovery Risk

Scanning many predicates increases the chance of noise that looks useful.
AS11 must report multiple-testing risk even before statistical corrections are
implemented. MVP diagnostics should include:

- total predicate vocabulary size;
- candidate count scanned;
- candidate count filtered;
- candidate count returned;
- evaluated positive and negative sample counts;
- warnings when candidate count is large relative to sample size;
- warnings when the best candidates are supported by very few examples;
- warnings when input paths come from bounded previews.

P-values, confidence intervals, false-discovery-rate controls, and correction
procedures may be future scope. The MVP must still avoid certainty language
and must not describe apparent lift as validated structure.

### Temporal Split And Stability Design

Temporal split validation should use chronological segments rather than random
mixing. Future validation modes may include:

- discovery segment versus validation segment;
- old versus recent data;
- rolling chronological folds;
- market-regime or volatility segments when those labels exist;
- symbol/timeframe splits as later cross-dataset scope.

AS11 MVP reports stability as `unknown` because split validation is not yet
implemented, but the architecture reserves fields for split metrics. Future
reports should include per-split support, precision, recall, lift, baseline
positive rate, and degradation warnings.

Rule stability statuses:

- `stable`: metrics and support survive configured splits.
- `unstable`: metrics degrade materially or appear in only one segment.
- `unknown`: no split validation was supplied or implemented.
- `insufficient_data`: split sample sizes are too small for a useful claim.

### Family Separation

Family separation describes how well a candidate distinguishes one cohort from
another. Examples:

- family A versus family B;
- family A success versus family A failure;
- true POI versus false signal;
- road X versus road Y;
- positive outcome versus background/non-event windows.

Separation is diagnostic. It can explain how candidate conditions differ
between cohorts, but it is not a trading signal and does not imply a profitable
entry or exit rule.

### Explainability Requirements

Every candidate must be human-readable. Candidate reports should include:

- rule key and display name;
- predicates with component keys, operators, values, and path offsets;
- source component metadata when available;
- AS10 metric summary;
- support and sample-limit context;
- ranking score and score components if scoring exists;
- guardrail pass/fail details;
- warnings, blockers, and errors.

Opaque score-only candidates are not acceptable. If a candidate cannot explain
which conditions it uses and why it survived pruning, it should not be
returned.

### Relationship To AS8, AS9, And AS10

AS8 owns POI occurrence and family membership preview. AS11 may consume AS8
context indirectly through AS10 comparison cohorts, but it must not recompute
POIs or family memberships.

AS9 owns genome component encoding and path construction. AS11 derives its
predicate vocabulary from supplied AS9 genome path reports or AS10 cohorts. It
must not rebuild genome paths or re-encode components.

AS10 owns explicit rule testing and metric computation. AS11 should call or
reuse AS10 evaluation rather than duplicating support, precision, recall, lift,
false-positive, false-negative, or sample-limit logic. AS11 candidate output
should include AS10 metric summaries.

### Accepted AS11 Backend Behavior

AS11 implements the first conservative backend candidate scan layer:

AS11 - Bounded Rule Candidate Scan Backend

- backend-only;
- read-only;
- no persistence;
- no GUI;
- consumes AS10 comparison set definitions and AS9 genome path reports or AS10
  cohorts;
- uses `AnalysisSuiteWhiteBoxRuleTester` for rule evaluation and metrics;
- builds a bounded predicate vocabulary with
  `AnalysisSuitePredicateVocabularyItem` and
  `AnalysisSuitePredicateVocabularyReport`;
- scans single-predicate candidates only;
- represents returned candidates with `AnalysisSuiteRuleCandidate`;
- accepts `AnalysisSuiteRuleCandidateScanConfig`;
- returns `AnalysisSuiteRuleCandidateScanReport`;
- applies blockers, `min_total_support`, `min_positive_matches`, optional
  `min_precision`, optional `min_lift`, sample-size, sample-limit, leakage,
  and multiple-testing guardrails;
- ranks returned candidates with diagnostic lift/precision/support-weight
  scoring;
- returns bounded JSON-safe reports with default `100` and max `500`
  candidates;
- reports `candidate_count_scanned`, `candidate_count_filtered`,
  `candidate_count_returned`, support thresholds, sample-limit warnings, and
  stability status;
- reports stability as `unknown` unless temporal split validation is actually
  implemented.

Predicate vocabulary generation uses observed AS9 genome path component values
inside AS10 comparison cohorts. Symbolic, boolean, categorical, and
static-bin-like values become `equals` predicates by default. Configured scans
may include `not_equals`, `is_null`, and `not_null`. Numeric threshold mining is
skipped by default when `numeric_threshold_policy = "none"`; AS11 does not fit
quantiles or adaptive thresholds. Positive path offsets are blocked to prevent
future-snapshot leakage. Negative offsets are used only when explicitly
enabled. Components marked leaky or future-derived by metadata are skipped.

Each vocabulary item becomes one AS10 `AnalysisSuiteWhiteBoxRuleDefinition`.
AS11 calls `AnalysisSuiteWhiteBoxRuleTester.test_rule(...)` and consumes AS10
metric summaries; it does not duplicate support, precision, recall, lift,
false-positive, false-negative, sample-limit, or diagnostic-gating formulas.
Candidate scores are diagnostic ranking aids only. They are not alpha,
profitability, trading performance, or signals.

AS11 reports sample-limited input honestly, warns that no multiple-testing
correction is applied, and reports `stability_status = "unknown"` because
temporal stability validation is not performed in AS11 MVP. Temporal stability,
holdout validation, rule survival, cautious conjunction expansion, broad
candidate mining, and AS10/AS11 GUI controls remain future work.

### Future GUI Implications

No AS11 GUI is part of the accepted AS11 backend patch. A future GUI should
expose candidate scan reports only after the backend contract is stable and
manually reviewed. The GUI should collect scan configuration, render backend
candidate reports, and preserve backend ownership of predicate vocabulary,
metrics, ranking, pruning, and warnings. The GUI must not generate candidates
locally, compute metrics, infer feature truth from raw CSV headers, persist
candidates, create stores, produce signals, or run backtests.

### Proposed Patch Sequence After AS11

Recommended sequence:

1. AS11D - Docs sync.
   - Document accepted AS11 backend behavior after implementation.
2. AS12-AUDIT - Candidate Validation / Temporal Stability Architecture.
   - Define chronological split validation, holdout validation, rule survival,
     stability scoring, degradation warnings, and criteria for any later
     conjunction expansion.

## AS12-AUDIT And AS12 - Candidate Temporal Validation

AS12-AUDIT defines the architecture for validating AS11 rule candidates across
time. AS12 implements the first conservative backend layer:
`AnalysisSuiteCandidateTemporalValidator`. It is backend-only, read-only, and
non-persistent. It does not add GUI controls, stores, model training, signal
generation, backtesting, PnL validation, order generation, trading execution,
neural agents, RL Decisor logic, artifact calculation, recipe execution,
Analysis Database mutation, OHLCV repair, or Data Manager mutation.

AS11 can rank a candidate from one bounded sample, but ranking is not evidence
that the candidate survives time. AS12 asks whether a candidate remains
diagnostically useful outside the slice where it was found.

### Candidate Validation

Candidate validation is diagnostic retesting of AS11 candidates across
independent or chronologically separated data segments. It measures robustness
of an already-defined candidate rule. It does not prove profitability, create
trading signals, persist strategies, or validate executable trading behavior.

Validation reports evidence quality: whether support survives, whether lift or
precision degrades, whether false positives expand, and whether validation data
is sufficient for the claim being made.

### Temporal Stability

Temporal stability is consistency of candidate metrics across ordered time
segments. Useful segment comparisons include:

- discovery period versus validation period;
- older history versus recent history;
- first half versus second half;
- rolling chronological windows;
- expanding chronological windows;
- recent holdout windows;
- custom explicitly supplied segments.

Metrics to compare include support, precision, recall, lift,
false-positive rate, false-negative rate, baseline positive rate, candidate
score, and candidate rank. Stability is diagnostic metadata only. It is not
alpha, profitability, or trading performance.

### Validation Splits

Supported split concepts for architecture:

- `chronological_holdout`: earlier rows are discovery/reference, later rows
  are validation/holdout.
- `discovery_validation`: explicit discovery and validation segment
  definitions supplied by the caller.
- `rolling_windows`: fixed-width ordered windows evaluated separately.
- `expanding_windows`: growing discovery windows with later validation
  windows.
- `recent_holdout`: a final recent segment reserved for out-of-sample
  diagnostics.
- `custom_segments`: caller-provided segment keys and timestamp ranges.

The accepted AS12 backend MVP uses `chronological_holdout`. Random shuffling
is not part of the time-series MVP because it can mix future and past market
conditions in ways that hide temporal failure. True validation must keep later
data out of discovery/reference metrics.

### Rule Survival

Rule survival means a candidate continues to meet explicit diagnostic
thresholds in validation segments. Suggested survival statuses:

- `survived`: validation support and metrics remain above configured
  thresholds.
- `degraded`: the rule still has evidence but lift, precision, recall,
  support, or false-positive behavior materially worsens.
- `failed`: validation metrics fall below required thresholds or false
  positives become unacceptable.
- `insufficient_data`: one or more validation segments are too small for a
  useful claim.
- `unknown`: timestamps, splits, or validation inputs are missing.

Survival checks should include validation support, validation positive matches,
precision, lift, false-positive rate, and configured retention thresholds
against discovery/reference metrics.

### Metric Degradation

Metric degradation compares validation metrics against discovery/reference
metrics. Examples:

- precision degradation;
- lift degradation;
- recall degradation;
- support degradation;
- candidate score degradation;
- rank degradation.

For example, discovery lift of `3.0` and validation lift of `1.2` is a `60%`
lift degradation. Degradation thresholds must be explicit in future backend
configuration. Degradation warnings are diagnostics, not trading loss or PnL
statements.

### Stability Score

AS12 stability score summarizes validation quality with clear
components:

- validation support adequacy;
- positive-match adequacy;
- precision retention;
- lift retention;
- recall retention;
- false-positive-rate stability;
- consistency across segments;
- penalties for insufficient data;
- penalties for sample-limited input.

The stability score is a ranking and review aid. It is not alpha,
profitability, tradability, or a signal.

### Segment-Level Reports

AS12 reports expose each evaluated segment instead of hiding validation
inside a single aggregate. Segment report fields should include:

- `segment_key`;
- `start_ts_ms`;
- `end_ts_ms`;
- `path_count`;
- `positive_total`;
- `negative_total`;
- AS10 metric summary;
- blockers;
- warnings.

Segment reports make it clear when a candidate works only in one historical
slice or when validation support disappears outside the discovery/reference
period.

### Relationship To AS10 And AS11

AS10 tests a specific rule against a specific comparison set. AS11 proposes
single-predicate candidate rules and includes AS10 metric summaries. AS12
validates already-defined rules or AS11 candidate reports across time segments.

AS12 reuses `AnalysisSuiteWhiteBoxRuleTester` against split comparison sets.
It does not reimplement support, precision, recall, lift, false-positive,
false-negative, baseline-rate, sample-limit, or diagnostic gating formulas. It
does not rescan candidate vocabularies.

### Split Construction

AS12 split construction starts from an AS10 comparison set whose positive and
negative cohorts contain path objects with `anchor_ts_ms`. Validation segments
are built by assigning cohort paths to timestamp ranges.

If timestamps are missing, AS12 blocks chronological validation or returns
`unknown` / `insufficient_data` with warnings. It must not infer chronology
from row order alone unless a later contract explicitly declares row order as
timestamp order.

### Sample-Limited Inputs

AS9, AS10, and AS11 reports may be bounded previews. If validation uses
sample-limited inputs, AS12 must propagate that context and mark validation as
sample-limited. Sample-limited validation can still be useful for workflow
inspection, but it must not be described as full historical proof.

### Multiple-Testing Risk

AS11 candidate scanning creates multiple-testing and false-discovery risk.
AS12 validation can reduce confidence in unstable candidates, but it does not
erase the fact that many candidates may have been scanned. AS12 reports
preserve AS11 multiple-testing warnings and include candidate-scan context when
available.

### Candidate Promotion And Demotion

Candidate review statuses are diagnostic:

- `candidate`: generated or supplied candidate has not been validated.
- `validation_survived`: candidate survived configured validation checks.
- `validation_degraded`: candidate weakened but remains reviewable.
- `validation_failed`: candidate failed validation thresholds.
- `insufficient_data`: validation data is too small or incomplete.
- `rejected`: candidate is no longer useful under configured diagnostics.
- `review`: candidate needs manual review because warnings or mixed segment
  results prevent a clean status.

Promotion does not create a trading signal, saved strategy, order rule, or
Research Suite validation result.

### Accepted AS12 Backend MVP

Accepted AS12 backend behavior:

- backend-only;
- read-only;
- no persistence;
- no GUI;
- uses `AnalysisSuiteCandidateTemporalValidator`;
- provides `AnalysisSuiteTemporalValidationSegment`;
- provides `AnalysisSuiteTemporalValidationConfig`;
- provides `AnalysisSuiteCandidateSegmentValidation`;
- provides `AnalysisSuiteCandidateMetricDegradation`;
- provides `AnalysisSuiteCandidateTemporalValidationResult`;
- provides `AnalysisSuiteCandidateTemporalValidationReport`;
- consumes AS10 comparison sets and AS11 candidate reports;
- reuses AS10 rule testing for per-segment metrics;
- builds `chronological_holdout` splits from `anchor_ts_ms`;
- reports discovery/reference metrics and validation/holdout metrics;
- reports segment metrics, survival status, metric degradation, stability
  score, blockers, warnings, and sample-limit context;
- preserves AS11 multiple-testing warnings;
- caps validated candidates at default `100` and max `500`;
- reports `candidate_count_input`, `candidate_count_validated`,
  `candidate_count_survived`, `candidate_count_degraded`,
  `candidate_count_failed`, `candidate_count_insufficient_data`, and
  `candidate_count_unknown`;
- does not backtest, compute PnL, generate signals, train models, create
  stores, mutate databases, persist validated rules, rescan candidates, mine
  new candidates, or perform conjunction expansion.

### Future GUI Implications

No AS12 GUI is part of AS12. A later GUI should expose validation reports only
after a separate GUI contract is designed and reviewed. The GUI should
collect validation intent and render backend reports; it must not split cohorts
itself, compute AS10 metrics, assign survival statuses, compute stability
scores, persist validated rules, generate signals, or run backtests.

### Proposed Patch Sequence After AS12D

Recommended sequence:

1. AS12D - Docs sync.
   - Document accepted AS12 backend behavior after implementation.
2. AS13-AUDIT - Validated Rule Review / Promotion Architecture.
   - Define how validated candidates are reviewed, compared, grouped, and
     prepared for later Research Suite validation without becoming trading
     signals.

## Out-Of-Scope Boundaries

AS8, AS9, AS10, AS11, AS12, AS-GUI-1, AS-GUI-2, AS-GUI-3, AS10-AUDIT,
AS11-AUDIT, and AS12-AUDIT do not add:

- GUI category builder.
- AS10 GUI controls.
- AS11 GUI controls.
- AS12 GUI controls.
- Persistent POI family store.
- POI definition or POI family definition persistence.
- Persistent genome definition or genome path persistence.
- Persistent genome stores.
- Persistent rule definitions, comparison sets, rule reports, or rule stores.
- Persistent candidate validation reports or validated rule stores.
- Candidate rescanning.
- New candidate mining.
- Persistent binner policies.
- Analysis Project/Run/Report stores.
- Road classification.
- Full outcome distribution measurement.
- Dynamic Binner fitting.
- Full Dynamic Binner implementation.
- Full Variation Analyzer implementation.
- Automatic rule discovery.
- Implemented white-box rule discovery.
- Broad candidate mining.
- Conjunction mining.
- Conjunction expansion.
- Itemset mining.
- Recursive search.
- Genetic programming.
- Rolling-window, expanding-window, or recent-holdout temporal validation beyond
  the AS12 chronological-holdout MVP.
- Backtesting engine.
- PnL or profit validation.
- Order generation.
- Trading execution.
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

1. AS-GUI-1D - Target / Feature / Diagnostic Preview UI docs sync.
   - Document accepted AS-GUI-1 behavior and preserve no-persistence/no-mutation
     boundaries.
2. Optional AS-GUI-POLISH-AUDIT.
   - Review layout and small usability issues found during manual exploration
     without changing backend contracts.
3. AS-GUI-2 - POI / Family Preview UI.
   - Implemented as the accepted read-only AS8 POI/family preview workflow.
4. AS-GUI-2D - POI / Family Preview UI docs sync.
   - Document accepted AS-GUI-2 behavior and preserve backend-owned policy and
     no-persistence/no-mutation boundaries.
5. AS-GUI-3 - Genome Path Preview UI.
   - Implemented as the accepted read-only AS9 genome/path preview workflow.
6. AS-GUI-3D - Genome Path Preview UI docs sync.
   - Document accepted AS-GUI-3 behavior and preserve backend-owned policy and
     no-persistence/no-mutation boundaries.
7. AS10-AUDIT - POI Family Comparison and White-Box Rule Discovery
   Architecture.
   - Defines comparison sets, rule testing, support, precision, recall, lift,
     false-positive rate, stability, and family separation.
8. AS10 - White-Box Rule Testing Backend.
   - Implemented as the accepted backend-only, read-only rule-testing MVP.
9. AS10D - Docs sync.
   - Document accepted AS10 backend behavior after implementation.
10. AS11-AUDIT - White-Box Rule Discovery / Candidate Mining Architecture.
    - Define bounded candidate generation and overfitting guardrails before
      deeper rule mining.
11. AS11 - Bounded Rule Candidate Scan Backend.
    - Implemented as the accepted backend-only, read-only single-predicate
      candidate scan.
12. AS11D - Docs sync.
    - Document accepted AS11 backend behavior after implementation.
13. AS12-AUDIT - Candidate Validation / Temporal Stability Architecture.
    - Define chronological split validation and rule survival before broader
      candidate mining or conjunction expansion.
14. AS12 - Candidate Temporal Validation Backend.
    - Implemented as the accepted backend-only, read-only chronological
      holdout candidate validation MVP.
15. AS12D - Docs sync.
    - Document accepted AS12 backend behavior after implementation.
16. AS13-AUDIT - Validated Rule Review / Promotion Architecture.
    - Future design boundary for reviewing validated candidates without
      turning them into trading signals.

Research Suite validation integration, neural refinement, and Decisor logic
remain later architecture tracks.
