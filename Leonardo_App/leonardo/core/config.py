from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib
from typing import Any, Mapping


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    json: bool = True


@dataclass(frozen=True)
class AuditConfig:
    enabled: bool = True
    file_enabled: bool = True
    file_path: str = "./runs/audit.jsonl"
    memory_max_events: int = 2000


@dataclass(frozen=True)
class RuntimeConfig:
    shutdown_timeout_s: float = 10.0


@dataclass(frozen=True)
class AppConfig:
    profile: str = "default"
    logging: LoggingConfig = LoggingConfig()
    audit: AuditConfig = AuditConfig()
    runtime: RuntimeConfig = RuntimeConfig()


def _deep_set(d: dict[str, Any], path: list[str], value: Any) -> None:
    cur: dict[str, Any] = d
    for p in path[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[path[-1]] = value


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _deep_merge(dict(out[k]), v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _defaults_dict() -> dict[str, Any]:
    # Keep defaults explicit: predictable, testable.
    return {
        "profile": "default",
        "logging": {"level": "INFO", "json": True},
        "audit": {
            "enabled": True,
            "file_enabled": True,
            "file_path": "./runs/audit.jsonl",
            "memory_max_events": 2000,
        },
        "runtime": {"shutdown_timeout_s": 10.0},
    }


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def _apply_env_overrides(d: dict[str, Any], prefix: str = "LEONARDO__") -> dict[str, Any]:
    out = dict(d)

    prefix_u = prefix.upper()
    for key, raw in os.environ.items():
        # Case-insensitive prefix match (Windows-friendly)
        if not key.upper().startswith(prefix_u):
            continue

        # keep same slicing length; only case changed
        suffix = key[len(prefix):]
        path = suffix.split("__")
        if not path or any(not p for p in path):
            continue

        # Normalize nested keys to match our config dict keys
        path = [p.lower() for p in path]

        # Minimal typing: bool/int/float fallback to str
        val: Any = raw
        low = raw.strip().lower()
        if low in {"true", "false"}:
            val = (low == "true")
        else:
            try:
                if "." in raw:
                    val = float(raw)
                else:
                    val = int(raw)
            except ValueError:
                val = raw

        _deep_set(out, path, val)

    return out


def load_config(config_path: Path | None = None) -> AppConfig:
    """
    Layer order (last wins):
      1) defaults
      2) config file (TOML)
      3) env overrides (LEONARDO__...)
    """
    base = _defaults_dict()

    if config_path is None:
        # cross-platform-ish default
        config_path = Path.home() / ".leonardo" / "config.toml"

    file_cfg = _load_toml(config_path)
    merged = _deep_merge(base, file_cfg)
    merged = _apply_env_overrides(merged)

    # Build typed config
    logging_cfg = LoggingConfig(**merged.get("logging", {}))
    audit_cfg = AuditConfig(**merged.get("audit", {}))
    runtime_cfg = RuntimeConfig(**merged.get("runtime", {}))

    return AppConfig(
        profile=str(merged.get("profile", "default")),
        logging=logging_cfg,
        audit=audit_cfg,
        runtime=runtime_cfg,
    )
