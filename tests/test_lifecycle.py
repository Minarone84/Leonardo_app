import asyncio
from dataclasses import replace
from pathlib import Path

from leonardo.core.app import LeonardoApp
from leonardo.core.config import load_config


def test_startup_shutdown_smoke(tmp_path) -> None:
    cfg = load_config(config_path=Path("nonexistent.toml"))

    # Redirect audit file output into pytest temp dir (config is frozen/immutable)
    audit_path = tmp_path / "audit.jsonl"
    cfg = replace(cfg, audit=replace(cfg.audit, file_path=str(audit_path)))

    app = LeonardoApp(cfg)

    async def scenario() -> None:
        await app._startup()
        await app._shutdown(reason="test")

    asyncio.run(scenario())

    # If file audit is enabled, we expect the file to exist after shutdown.
    if cfg.audit.enabled and cfg.audit.file_enabled:
        assert audit_path.exists()
        assert audit_path.stat().st_size > 0
