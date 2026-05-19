from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseManifest
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recovery_planner import (
    ArtifactRecoveryPlanner,
    ArtifactRecoveryReport,
)
from leonardo.data.historical.artifact_recovery_regenerator import (
    ArtifactRecoveryRegenerationReport,
)
from leonardo.data.naming import MarketId


ArtifactRecoveryDatabaseRebuildStatus = Literal["rebuilt", "skipped", "blocked", "failed"]


@dataclass(frozen=True)
class ArtifactRecoveryDatabaseRebuildReport:
    """Structured report for Analysis Database rebuild after artifact recovery.

    This report is orchestration-only. It records whether a collection-linked
    Analysis Database was materialized after artifact recovery, while preserving
    strict store ownership over manifest and dataframe semantics.
    """

    market: MarketId
    collection_id: str
    source_database_id: str | None
    status: ArtifactRecoveryDatabaseRebuildStatus
    manifest: AnalysisDatabaseManifest | None = None
    recovery_report: ArtifactRecoveryReport | None = None
    blocked_reasons: tuple[str, ...] = ()
    error_text: str = ""
    skipped_reason: str = ""

    @property
    def rebuilt(self) -> bool:
        return self.status == "rebuilt"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def success(self) -> bool:
        return self.rebuilt

    def to_dict(self) -> dict[str, object]:
        return {
            "market": {
                "exchange": self.market.exchange,
                "market_type": self.market.market_type,
                "symbol": self.market.symbol,
                "timeframe": self.market.timeframe,
            },
            "collection_id": self.collection_id,
            "source_database_id": self.source_database_id,
            "status": self.status,
            "rebuilt": self.rebuilt,
            "skipped": self.skipped,
            "blocked": self.blocked,
            "failed": self.failed,
            "success": self.success,
            "blocked_reasons": list(self.blocked_reasons),
            "error_text": self.error_text,
            "skipped_reason": self.skipped_reason,
            "database_manifest": None if self.manifest is None else self.manifest.to_dict(),
            "recovery_report": None if self.recovery_report is None else self.recovery_report.to_dict(),
        }


class ArtifactRecoveryDatabaseRebuilder:
    """Rebuild collection-linked Analysis Databases after artifact recovery.

    Ownership boundaries:
    - ``ArtifactRecoveryPlanner`` owns read-only artifact/source status;
    - ``ArtifactRecoveryRegenerator`` owns artifact-regeneration orchestration;
    - this class decides whether database materialization is allowed;
    - ``AnalysisDatabaseStore`` owns manifest persistence and dataframe materialization.

    This class must not manually rewrite ``manifest.json``, materialize
    ``dataframe.csv`` itself, infer dataframe column contracts, or mutate saved
    artifact metadata.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        analysis_store: AnalysisDatabaseStore | None = None,
        planner: ArtifactRecoveryPlanner | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._analysis_store = analysis_store or AnalysisDatabaseStore(
            historical_root=self._historical_root
        )
        self._planner = planner or ArtifactRecoveryPlanner(
            historical_root=self._historical_root
        )
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root
        )

    def rebuild_for_collection_by_id(
        self,
        *,
        market: MarketId,
        collection_id: str,
        recovery_report: ArtifactRecoveryReport | None = None,
        regeneration_report: ArtifactRecoveryRegenerationReport | None = None,
        require_clean_recovery: bool = True,
        overwrite: bool = True,
    ) -> ArtifactRecoveryDatabaseRebuildReport:
        collection = self._collection_store.load_collection(
            market=market,
            collection_id=collection_id,
        )
        return self.rebuild_for_collection(
            collection,
            recovery_report=recovery_report,
            regeneration_report=regeneration_report,
            require_clean_recovery=require_clean_recovery,
            overwrite=overwrite,
        )

    def rebuild_for_collection(
        self,
        collection: ArtifactRecipeCollection,
        *,
        recovery_report: ArtifactRecoveryReport | None = None,
        regeneration_report: ArtifactRecoveryRegenerationReport | None = None,
        require_clean_recovery: bool = True,
        overwrite: bool = True,
    ) -> ArtifactRecoveryDatabaseRebuildReport:
        if not isinstance(collection, ArtifactRecipeCollection):
            raise TypeError(
                "rebuild_for_collection() expects an ArtifactRecipeCollection instance"
            )
        if recovery_report is not None and regeneration_report is not None:
            raise ValueError(
                "Pass either recovery_report or regeneration_report, not both."
            )

        source_database_id = collection.source_database_id
        if not source_database_id:
            return ArtifactRecoveryDatabaseRebuildReport(
                market=collection.market,
                collection_id=collection.collection_id,
                source_database_id=None,
                status="skipped",
                skipped_reason=(
                    "Artifact recipe collection is not linked to an Analysis Database."
                ),
            )

        resolved_recovery_report = self._resolve_recovery_report(
            collection=collection,
            recovery_report=recovery_report,
            regeneration_report=regeneration_report,
            require_clean_recovery=require_clean_recovery,
        )
        blocked_reasons = self._recovery_blockers(
            collection=collection,
            recovery_report=resolved_recovery_report,
            regeneration_report=regeneration_report,
            require_clean_recovery=require_clean_recovery,
        )
        if blocked_reasons:
            return ArtifactRecoveryDatabaseRebuildReport(
                market=collection.market,
                collection_id=collection.collection_id,
                source_database_id=source_database_id,
                status="blocked",
                recovery_report=resolved_recovery_report,
                blocked_reasons=blocked_reasons,
            )

        try:
            manifest = self._analysis_store.materialize_database(
                market=collection.market,
                database_id=source_database_id,
                overwrite=overwrite,
            )
        except Exception as exc:
            return ArtifactRecoveryDatabaseRebuildReport(
                market=collection.market,
                collection_id=collection.collection_id,
                source_database_id=source_database_id,
                status="failed",
                recovery_report=resolved_recovery_report,
                error_text=f"{type(exc).__name__}: {exc}",
            )

        return ArtifactRecoveryDatabaseRebuildReport(
            market=collection.market,
            collection_id=collection.collection_id,
            source_database_id=source_database_id,
            status="rebuilt",
            manifest=manifest,
            recovery_report=resolved_recovery_report,
        )

    def _resolve_recovery_report(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recovery_report: ArtifactRecoveryReport | None,
        regeneration_report: ArtifactRecoveryRegenerationReport | None,
        require_clean_recovery: bool,
    ) -> ArtifactRecoveryReport | None:
        if recovery_report is not None:
            self._validate_recovery_report(collection=collection, recovery_report=recovery_report)
            return recovery_report

        if regeneration_report is not None:
            self._validate_regeneration_report(
                collection=collection,
                regeneration_report=regeneration_report,
            )
            return regeneration_report.post_recovery_report or regeneration_report.pre_recovery_report

        if require_clean_recovery:
            return self._planner.plan_collection(collection)
        return None

    def _recovery_blockers(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recovery_report: ArtifactRecoveryReport | None,
        regeneration_report: ArtifactRecoveryRegenerationReport | None,
        require_clean_recovery: bool,
    ) -> tuple[str, ...]:
        if not require_clean_recovery:
            return ()

        blockers: list[str] = []
        if regeneration_report is not None:
            if not regeneration_report.execution_success:
                blockers.append(
                    "Artifact regeneration execution did not complete successfully."
                )
            if (
                regeneration_report.post_recovery_report is None
                and not regeneration_report.pre_recovery_report.success
            ):
                blockers.append(
                    "Artifact regeneration report has no post-recovery plan confirming recovered artifacts."
                )

        if recovery_report is None:
            blockers.append("No recovery report is available to verify artifacts before database rebuild.")
            return tuple(blockers)

        if not recovery_report.success:
            blockers.append(
                "Recovery report is not clean; Analysis Database rebuild is blocked until artifacts are up to date."
            )
            blockers.extend(self._summarize_unclean_recovery(recovery_report))

        return tuple(blockers)

    def _summarize_unclean_recovery(
        self,
        recovery_report: ArtifactRecoveryReport,
    ) -> tuple[str, ...]:
        summary: list[str] = []
        if recovery_report.missing_count:
            summary.append(f"missing={recovery_report.missing_count}")
        if recovery_report.stale_count:
            summary.append(f"stale={recovery_report.stale_count}")
        if recovery_report.freshness_unknown_count:
            summary.append(f"freshness_unknown={recovery_report.freshness_unknown_count}")
        if recovery_report.blocked_count:
            summary.append(f"blocked={recovery_report.blocked_count}")
        if not summary:
            return ()
        return ("Unclean recovery counts: " + ", ".join(summary),)

    def _validate_recovery_report(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recovery_report: ArtifactRecoveryReport,
    ) -> None:
        if not isinstance(recovery_report, ArtifactRecoveryReport):
            raise TypeError("Expected an ArtifactRecoveryReport instance")
        if recovery_report.market != collection.market:
            raise ValueError("Recovery report market does not match collection market")
        if recovery_report.collection_id != collection.collection_id:
            raise ValueError(
                "Recovery report collection_id does not match collection collection_id"
            )

    def _validate_regeneration_report(
        self,
        *,
        collection: ArtifactRecipeCollection,
        regeneration_report: ArtifactRecoveryRegenerationReport,
    ) -> None:
        if not isinstance(regeneration_report, ArtifactRecoveryRegenerationReport):
            raise TypeError("Expected an ArtifactRecoveryRegenerationReport instance")
        if regeneration_report.market != collection.market:
            raise ValueError("Regeneration report market does not match collection market")
        if regeneration_report.collection_id != collection.collection_id:
            raise ValueError(
                "Regeneration report collection_id does not match collection collection_id"
            )
