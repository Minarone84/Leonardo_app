from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


class WorkspaceBatchMixin:
    def _defer_workspace_refresh(
        self,
        *,
        contracts: bool = False,
        labels: bool = False,
        sizes: bool = False,
        price: bool = False,
    ) -> None:
        self._deferred_contract_refresh = self._deferred_contract_refresh or bool(contracts)
        self._deferred_labels_refresh = self._deferred_labels_refresh or bool(labels)
        self._deferred_size_refresh = self._deferred_size_refresh or bool(sizes)
        self._deferred_price_refresh = self._deferred_price_refresh or bool(price)

    @contextmanager
    def _workspace_update_batch(self) -> Iterator[None]:
        outermost = self._workspace_update_depth == 0
        self._workspace_update_depth += 1
        if outermost and hasattr(self._model, "begin_change_batch"):
            try:
                self._model.begin_change_batch()
            except Exception:
                pass
        try:
            yield
        finally:
            self._workspace_update_depth = max(0, self._workspace_update_depth - 1)
            if not outermost:
                return
            try:
                if hasattr(self._model, "end_change_batch"):
                    try:
                        self._model.end_change_batch()
                    except Exception:
                        pass
            finally:
                self._flush_deferred_workspace_refreshes()

    def _flush_deferred_workspace_refreshes(self) -> None:
        if self._workspace_update_depth > 0:
            return

        contracts = bool(self._deferred_contract_refresh)
        labels = bool(self._deferred_labels_refresh)
        sizes = bool(self._deferred_size_refresh)
        price = bool(self._deferred_price_refresh)

        self._deferred_contract_refresh = False
        self._deferred_labels_refresh = False
        self._deferred_size_refresh = False
        self._deferred_price_refresh = False

        if contracts:
            self._refresh_aux_pane_bindings()
        if labels:
            self._refresh_studies_labels()
        if sizes:
            self._apply_default_sizes(force=True)
        if price and not contracts:
            self._refresh_price_pane()
