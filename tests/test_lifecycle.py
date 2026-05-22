import asyncio
from dataclasses import replace
from pathlib import Path

from leonardo.connection.exchange.registry import ExchangeRegistry
from leonardo.core.app import LeonardoApp
from leonardo.core.config import load_config
from leonardo.core.registry_keys import SVC_EXCHANGE_REGISTRY


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


def test_startup_registers_exchange_registry_as_capability_provider(tmp_path) -> None:
    cfg = load_config(config_path=Path("nonexistent.toml"))
    cfg = replace(cfg, audit=replace(cfg.audit, file_path=str(tmp_path / "audit.jsonl")))
    app = LeonardoApp(cfg)

    async def scenario() -> None:
        await app._startup()
        try:
            registry = app.context.get_service(SVC_EXCHANGE_REGISTRY, ExchangeRegistry)
            assert registry.supported_exchange_names() == ["bybit"]
            assert not app.context.is_lifecycle_service(SVC_EXCHANGE_REGISTRY)
        finally:
            await app._shutdown(reason="test")

    asyncio.run(scenario())
