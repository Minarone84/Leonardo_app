from __future__ import annotations

from leonardo.financial_tools.tool_contracts.contracts import (
    BehaviorContract,
    ConstructIOContract,
    OutputContract,
    OutputSignalContract,
    ParamContract,
    ToolContract,
)

NON_VISUAL = BehaviorContract(
    "non-visual",
    chart_renderable=False,
    supports_style=False,
    supports_pane_layout=False,
    supports_last_value=False,
)
OSC_CONSTRUCT = BehaviorContract(
    "oscillator-pane",
    chart_renderable=True,
    supports_style=True,
    supports_pane_layout=True,
    supports_last_value=True,
)

SOURCE_COLUMNS = ParamContract("source_columns", "str", default="close", label="Source Columns")
SOURCE = ParamContract("source", "str", default="close", label="Source")
FAST = ParamContract("fast", "str", default="", label="Fast Source")
MID = ParamContract("mid", "str", required=False, default="", label="Mid Source")
SLOW = ParamContract("slow", "str", default="", label="Slow Source")

CHAINABLE_SOURCE_FAMILIES = ("ohlc", "indicator", "oscillator", "construct")
CHAINABLE_NON_OHLC_SOURCE_FAMILIES = ("indicator", "oscillator", "construct")

UNARY_IO = ConstructIOContract(
    input_binding="unary_source",
    allowed_source_families=CHAINABLE_SOURCE_FAMILIES,
    source_compatibility="mixed_numeric",
    output_cardinality="single",
    output_role="plotted_line",
)
FS_IO = ConstructIOContract(
    input_binding="fast_slow",
    allowed_source_families=CHAINABLE_SOURCE_FAMILIES,
    source_compatibility="mixed_numeric",
    output_cardinality="one_or_more",
    output_role="plotted_line",
)
FMS_IO = ConstructIOContract(
    input_binding="fast_mid_slow",
    allowed_source_families=CHAINABLE_SOURCE_FAMILIES,
    source_compatibility="mixed_numeric",
    output_cardinality="one_or_more",
    output_role="plotted_line",
)
MULTI_IO = ConstructIOContract(
    input_binding="multi_source",
    allowed_source_families=CHAINABLE_SOURCE_FAMILIES,
    source_compatibility="mixed_numeric",
    output_cardinality="matches_inputs",
    output_role="plotted_line",
)

def line(resolver: str) -> OutputContract:
    return OutputContract(
        structure="line-series",
        naming_resolver=resolver,
        signals=(OutputSignalContract(),),
    )

def multi(resolver: str, *, dynamic: bool = True) -> OutputContract:
    return OutputContract(
        structure="multi-line-series",
        naming_resolver=resolver,
        dynamic_signals=dynamic,
    )

CONSTRUCT_CONTRACTS: dict[str, ToolContract] = {
    "dynamic_binning": ToolContract(
        family="construct",
        key="dynamic_binning",
        title="Dynamic Binning",
        aliases=("dynamic_binning_analysis",),
        params=(
            SOURCE_COLUMNS,
            ParamContract("window", "int", default=10, minimum=1),
            ParamContract("multiplier", "float", required=False, default=1.0, minimum=0.000001),
            ParamContract("floor_quantile", "float", required=False, default=0.05, minimum=0.0, maximum=1.0),
            ParamContract("global_min_step", "float", required=False, default=1e-12, minimum=0.0),
            ParamContract("quantile_method", "str", required=False, default="nearest", choices=("nearest", "lower", "higher", "midpoint", "linear")),
            ParamContract("n_bins", "int", required=False, default=15, minimum=1),
            ParamContract("boundary_eps", "float", required=False, default=1e-12, minimum=0.0),
        ),
        behavior=NON_VISUAL,
        output=OutputContract(
            structure="analysis-only",
            naming_resolver="construct:dynamic_binning",
            accepts_empty_render_output=True,
        ),
        description="Non-visual construct that fits deterministic signed bins.",
    ),
    "derivative": ToolContract(
        family="construct",
        key="derivative",
        title="Derivatives",
        aliases=("derivative_analysis",),
        params=(ParamContract("order", "int", required=False, default=1, minimum=1, maximum=2),),
        behavior=OSC_CONSTRUCT,
        construct_io=UNARY_IO,
        output=line("construct:derivative"),
        form_variant="construct_unary_source",
        description="Unary construct computing first or second derivative.",
    ),
    "angle": ToolContract(
        family="construct",
        key="angle",
        title="Angles",
        aliases=("angle_analysis",),
        params=(ParamContract("unit", "str", required=False, default="deg", choices=("deg", "rad")),),
        behavior=OSC_CONSTRUCT,
        construct_io=UNARY_IO,
        output=line("construct:angle"),
        form_variant="construct_unary_source",
        description="Unary construct computing the canonical angle of the selected source.",
    ),
    "braids": ToolContract(
        family="construct",
        key="braids",
        title="Braids",
        params=(FAST, MID, SLOW, ParamContract("tie_policy", "str", required=False, default="carry", choices=("carry", "drop"))),
        behavior=OSC_CONSTRUCT,
        construct_io=ConstructIOContract(
            input_binding="fast_mid_slow",
            allowed_source_families=CHAINABLE_NON_OHLC_SOURCE_FAMILIES,
            source_compatibility="same_family",
            output_cardinality="one_or_more",
            output_role="state_series",
        ),
        output=OutputContract(
            structure="multi-line-series",
            naming_resolver="construct:braids",
            dynamic_signals=True,
            signals=(
                OutputSignalContract(
                    signal_type="signal",
                    renderable=True,
                    analysis_usable=True,
                    default_visible=True,
                    label="Braid Ambient State",
                    description="Categorical braid ordering state series.",
                    semantic_role="state",
                    value_type="categorical",
                    can_drive_style_rules=True,
                ),
                OutputSignalContract(
                    signal_type="signal",
                    renderable=False,
                    analysis_usable=True,
                    default_visible=False,
                    label="Braid Width",
                    description="Total braid envelope spread. Retained for analysis/chaining, not chart rendering.",
                    semantic_role="analysis",
                    value_type="numeric",
                ),
                OutputSignalContract(
                    signal_type="signal",
                    renderable=False,
                    analysis_usable=True,
                    default_visible=False,
                    label="Braid Compression",
                    description="Minimum pairwise braid separation. Retained for analysis/chaining, not chart rendering.",
                    semantic_role="analysis",
                    value_type="numeric",
                ),
            ),
        ),
        form_variant="construct_fms",
        description="Braid structural construct emitting ambient state, width, and compression.",
    ),
    "braid_instability": ToolContract(
        family="construct",
        key="braid_instability",
        title="Braid Instability",
        params=(FAST, MID, SLOW, ParamContract("n", "int", required=False, default=5, minimum=1)),
        behavior=OSC_CONSTRUCT,
        construct_io=ConstructIOContract(
            input_binding="fast_mid_slow",
            allowed_source_families=CHAINABLE_NON_OHLC_SOURCE_FAMILIES,
            source_compatibility="same_family",
            output_cardinality="single",
            output_role="plotted_line",
        ),
        output=line("construct:braid_instability"),
        form_variant="construct_fms",
        description="Temporal braid-stability construct measuring rolling raw braid-state churn.",
    ),
    "delta": ToolContract(
        family="construct",
        key="delta",
        title="Delta",
        params=(
            FAST,
            SLOW,
            ParamContract("mode", "str", required=False, default="abs", choices=("abs", "pct")),
            ParamContract("eps", "float", required=False, default=1e-12, minimum=0.0),
        ),
        behavior=OSC_CONSTRUCT,
        construct_io=FS_IO,
        output=multi("construct:delta"),
        form_variant="construct_fs",
        description="Directional relational construct computing fast-minus-slow.",
    ),
    "trap_area": ToolContract(
        family="construct",
        key="trap_area",
        title="Trap Area",
        params=(FAST, MID, SLOW, ParamContract("zero_eps", "float", required=False, default=0.0, minimum=0.0)),
        behavior=OSC_CONSTRUCT,
        construct_io=FMS_IO,
        output=multi("construct:trap_area"),
        form_variant="construct_fms",
        description="Cumulative trapezoidal area between ordered faster/slower signal pairs.",
    ),
    "percent_span_angle": ToolContract(
        family="construct",
        key="percent_span_angle",
        title="Percent Span Angle",
        aliases=("percent_angle", "percent_angle_analysis", "percent_span_angle_analysis"),
        params=(SOURCE_COLUMNS, ParamContract("window", "int", default=10, minimum=1), ParamContract("unit", "str", required=False, default="deg", choices=("deg", "rad"))),
        behavior=OSC_CONSTRUCT,
        construct_io=MULTI_IO,
        output=multi("construct:percent_span_angle"),
        form_variant="construct_multi_source",
        description="Windowed percent-span angle on selected source columns.",
    ),
    "angle_momentum": ToolContract(
        family="construct",
        key="angle_momentum",
        title="Angle Momentum",
        params=(SOURCE_COLUMNS, ParamContract("n", "int", required=False, default=3, minimum=1)),
        behavior=OSC_CONSTRUCT,
        construct_io=MULTI_IO,
        output=multi("construct:angle_momentum"),
        form_variant="construct_multi_source",
        description="Signed average angle change per bar on selected angle-like source columns.",
    ),
}
