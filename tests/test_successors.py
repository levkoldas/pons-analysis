from types import SimpleNamespace

from pons_analysis import MigrationCut, Pons
from pons_analysis.core.models import RpcLog
from pons_analysis.evidence.successors import collect_successors
from pons_analysis.storage.store import ArtifactStore

ROOT = "0x" + "11" * 20
UNRELATED = "0x" + "33" * 20


def _log(source, destination, index):
    return RpcLog(
        address="0x" + "22" * 20,
        topics=[
            "0x" + "dd" * 32,
            "0x" + "0" * 24 + source[2:],
            "0x" + "0" * 24 + destination[2:],
        ],
        data="0x" + "0" * 62 + "01",
        blockNumber=1,
        transactionHash="0x" + f"{index:064x}",
        transactionIndex=0,
        logIndex=index,
    )


class FakeRpc:
    def __init__(self, curve):
        self.curve = curve

    def latest_block(self):
        return 1

    def block(self, number):
        return SimpleNamespace(number=number, timestamp=1)

    def receipt(self, tx_hash):
        return SimpleNamespace(
            block_number=1,
            succeeded=True,
            model_dump=lambda **kwargs: {"transactionHash": tx_hash},
        )

    def logs(self, token, start, end, topics):
        sources = topics[1] if len(topics) == 2 else []
        recipients = topics[2] if len(topics) == 3 else []
        rows = []
        if ROOT in sources:
            rows.append(_log(ROOT, self.curve, 1))
        if ROOT in recipients:
            rows.append(_log(self.curve, ROOT, 2))
        if self.curve in sources:
            rows.append(_log(self.curve, UNRELATED, 3))
        return rows


def test_successor_walk_excludes_curve(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    profile = Pons.launch(
        token="0x" + "22" * 20,
        supply=10**27,
        start_block=1,
        start_timestamp=0,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    result = collect_successors(
        FakeRpc(profile.curve),
        store,
        profile,
        start_block=1,
        wallets=[ROOT],
        max_generations=3,
    )
    assert result["wallets"] == 1
    assert store.read_json("evidence/successors/tracked_wallets.json") == [ROOT]
