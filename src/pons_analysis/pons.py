"""The public PONS protocol facade."""

from pons_analysis.core.models import Launch, MigrationCut, PonsProtocol
from pons_analysis.discovery import resolve_pons_launch
from pons_analysis.ports import Rpc


class Pons:
    """PONS mainnet protocol and launch construction/discovery helpers."""

    protocol = PonsProtocol()

    @classmethod
    def launch(
        cls,
        *,
        token: str,
        supply: int,
        start_block: int,
        start_timestamp: int,
        migration: MigrationCut | None = None,
        decimals: int = 18,
        launch_start_block: int | None = None,
        pool_id: str | None = None,
        creator_tax_bps: int | None = None,
        curve: str | None = None,
        windows: tuple[int, ...] | None = None,
    ) -> Launch:
        return cls.protocol.launch(
            token=token,
            supply=supply,
            decimals=decimals,
            start_block=start_block,
            start_timestamp=start_timestamp,
            launch_start_block=launch_start_block,
            migration=migration,
            pool_id=pool_id,
            creator_tax_bps=creator_tax_bps,
            curve=curve,
            windows=windows,
        )

    @classmethod
    def resolve(
        cls,
        token: str,
        *,
        rpc: Rpc,
        migration: MigrationCut | None = None,
        launch_start_block: int | None = None,
        pool_id: str | None = None,
        supply: int | None = None,
        decimals: int | None = None,
        creator_tax_bps: int | None = None,
        head: int | None = None,
    ) -> Launch:
        return resolve_pons_launch(
            cls.protocol,
            token,
            rpc,
            migration=migration,
            launch_start_block=launch_start_block,
            pool_id=pool_id,
            supply=supply,
            decimals=decimals,
            creator_tax_bps=creator_tax_bps,
            head=head,
        )


__all__ = ["Pons", "PonsProtocol"]
