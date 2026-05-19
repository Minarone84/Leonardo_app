from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

ToolExecutionEnvironment = Literal["historical", "realtime"]
SUPPORTED_EXECUTION_ENVIRONMENTS: tuple[str, ...] = ("historical", "realtime")
DEFAULT_EXECUTION_ENVIRONMENT: ToolExecutionEnvironment = "historical"


def normalize_execution_environment(value: str | None) -> ToolExecutionEnvironment:
    """Return the canonical execution-environment token.

    Execution environment is runtime context. It is intentionally separate from
    tool parameters, canonical naming, saved artifact identity, and render keys.
    """

    if value is None:
        return DEFAULT_EXECUTION_ENVIRONMENT
    normalized = str(value).strip().lower()
    if normalized == "real_time":
        normalized = "realtime"
    if normalized not in SUPPORTED_EXECUTION_ENVIRONMENTS:
        raise ValueError(
            f"unsupported tool execution environment {value!r}; "
            f"expected one of {SUPPORTED_EXECUTION_ENVIRONMENTS}"
        )
    return normalized  # type: ignore[return-value]


def normalize_supported_environments(values: tuple[str, ...]) -> tuple[ToolExecutionEnvironment, ...]:
    if not values:
        raise ValueError("supported execution environments must not be empty")
    return tuple(normalize_execution_environment(value) for value in values)


@dataclass(frozen=True)
class ToolExecutionContext:
    """Runtime execution context for a financial-tool calculation.

    This context may influence how a runtime computes when the tool explicitly
    supports different historical/realtime semantics. It must not become part of
    normal tool params, canonical output naming, saved artifact identity, or
    renderer-facing identity.
    """

    environment: ToolExecutionEnvironment = DEFAULT_EXECUTION_ENVIRONMENT
    dependency_versions: Mapping[str, Any] = field(default_factory=dict)
    runtime_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment", normalize_execution_environment(self.environment))


def ensure_environment_supported(
    *,
    tool_key: str,
    environment: str,
    supported_environments: tuple[str, ...],
) -> ToolExecutionEnvironment:
    normalized_environment = normalize_execution_environment(environment)
    normalized_supported = normalize_supported_environments(tuple(supported_environments))
    if normalized_environment not in normalized_supported:
        raise ValueError(
            f"financial tool {tool_key!r} does not support execution environment "
            f"{normalized_environment!r}; supported environments: {normalized_supported}"
        )
    return normalized_environment
