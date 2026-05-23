from __future__ import annotations

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

from leonardo.core.registry_keys import SVC_HISTORICAL_OHLCV_MAINTENANCE
from leonardo.data.historical.dataset_service import DatasetId
from leonardo.gui.core_bridge import CoreBridge


class _FakeMaintenanceService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def list_ohlcv_datasets(self) -> tuple[str, ...]:
        self.calls.append(("list", None))
        return ("dataset",)

    def inspect_ohlcv(self, dataset_id: DatasetId) -> tuple[str, DatasetId]:
        self.calls.append(("inspect", dataset_id))
        return ("inspect", dataset_id)

    def validate_ohlcv(self, dataset_id: DatasetId) -> tuple[str, DatasetId]:
        self.calls.append(("validate", dataset_id))
        return ("validate", dataset_id)

    def plan_ohlcv_repair(self, dataset_id: DatasetId) -> tuple[str, DatasetId]:
        self.calls.append(("plan_repair", dataset_id))
        return ("plan_repair", dataset_id)

    async def execute_ohlcv_repair(self, ctx: object, dataset_id: DatasetId, plan: object) -> tuple[str, DatasetId, object]:
        self.calls.append(("execute_repair", dataset_id))
        return ("execute_repair", dataset_id, plan)

    def delete_ohlcv(self, dataset_id: DatasetId) -> tuple[str, DatasetId]:
        self.calls.append(("delete", dataset_id))
        return ("delete", dataset_id)

    def rebuild_ohlcv_metadata(self, dataset_id: DatasetId) -> tuple[str, DatasetId]:
        self.calls.append(("rebuild", dataset_id))
        return ("rebuild", dataset_id)


class _Bridge:
    _historical_ohlcv_maintenance_service = CoreBridge._historical_ohlcv_maintenance_service
    list_historical_ohlcv_datasets = CoreBridge.list_historical_ohlcv_datasets
    inspect_historical_ohlcv_dataset = CoreBridge.inspect_historical_ohlcv_dataset
    validate_historical_ohlcv_dataset = CoreBridge.validate_historical_ohlcv_dataset
    plan_historical_ohlcv_repair = CoreBridge.plan_historical_ohlcv_repair
    execute_historical_ohlcv_repair = CoreBridge.execute_historical_ohlcv_repair
    delete_historical_ohlcv_dataset = CoreBridge.delete_historical_ohlcv_dataset
    rebuild_historical_ohlcv_metadata = CoreBridge.rebuild_historical_ohlcv_metadata

    def __init__(self, service: _FakeMaintenanceService) -> None:
        self._service = service
        self.context = SimpleNamespace(get_service=self._get_service)

    def _get_service(self, key: str, _expected_type: object) -> object:
        assert key == SVC_HISTORICAL_OHLCV_MAINTENANCE
        return self._service

    def submit(self, coro: Any) -> Future[Any]:
        fut: Future[Any] = Future()
        try:
            fut.set_result(asyncio.run(coro))
        except BaseException as exc:
            fut.set_exception(exc)
        return fut


def test_core_bridge_lists_ohlcv_datasets_through_maintenance_service() -> None:
    service = _FakeMaintenanceService()
    bridge = _Bridge(service)

    result = CoreBridge.list_historical_ohlcv_datasets(bridge).result()

    assert result == ("dataset",)
    assert service.calls == [("list", None)]


def test_core_bridge_inspects_ohlcv_dataset_with_dataset_identity() -> None:
    service = _FakeMaintenanceService()
    bridge = _Bridge(service)

    kind, dataset_id = CoreBridge.inspect_historical_ohlcv_dataset(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="LINKUSDT",
        timeframe="1M",
    ).result()

    assert kind == "inspect"
    assert dataset_id == DatasetId("bybit", "linear", "LINKUSDT", "1M")


def test_core_bridge_validates_ohlcv_dataset_with_dataset_identity() -> None:
    service = _FakeMaintenanceService()
    bridge = _Bridge(service)

    kind, dataset_id = CoreBridge.validate_historical_ohlcv_dataset(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="LINKUSDT",
        timeframe="1m",
    ).result()

    assert kind == "validate"
    assert dataset_id == DatasetId("bybit", "linear", "LINKUSDT", "1m")


def test_core_bridge_plans_ohlcv_repair_with_dataset_identity() -> None:
    service = _FakeMaintenanceService()
    bridge = _Bridge(service)

    kind, dataset_id = CoreBridge.plan_historical_ohlcv_repair(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="LINKUSDT",
        timeframe="1m",
    ).result()

    assert kind == "plan_repair"
    assert dataset_id == DatasetId("bybit", "linear", "LINKUSDT", "1m")


def test_core_bridge_executes_ohlcv_repair_with_dataset_identity_and_plan() -> None:
    service = _FakeMaintenanceService()
    bridge = _Bridge(service)
    plan = object()

    kind, dataset_id, returned_plan = CoreBridge.execute_historical_ohlcv_repair(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="LINKUSDT",
        timeframe="1m",
        plan=plan,
    ).result()

    assert kind == "execute_repair"
    assert dataset_id == DatasetId("bybit", "linear", "LINKUSDT", "1m")
    assert returned_plan is plan


def test_core_bridge_deletes_ohlcv_dataset_with_dataset_identity() -> None:
    service = _FakeMaintenanceService()
    bridge = _Bridge(service)

    kind, dataset_id = CoreBridge.delete_historical_ohlcv_dataset(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="LINKUSDT",
        timeframe="1M",
    ).result()

    assert kind == "delete"
    assert dataset_id == DatasetId("bybit", "linear", "LINKUSDT", "1M")


def test_core_bridge_rebuilds_ohlcv_metadata_with_dataset_identity() -> None:
    service = _FakeMaintenanceService()
    bridge = _Bridge(service)

    kind, dataset_id = CoreBridge.rebuild_historical_ohlcv_metadata(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="LINKUSDT",
        timeframe="1M",
    ).result()

    assert kind == "rebuild"
    assert dataset_id == DatasetId("bybit", "linear", "LINKUSDT", "1M")
