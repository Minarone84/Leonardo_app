from pathlib import Path

from leonardo.core.config import load_config


def test_env_override_logging_level(monkeypatch) -> None:
    monkeypatch.setenv("LEONARDO__logging__level", "DEBUG")
    cfg = load_config(config_path=Path("nonexistent.toml"))
    assert cfg.logging.level == "DEBUG"
