import asyncio
from types import SimpleNamespace
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.world_graphs.repository import _live_graph_model_config


class _ScalarResult:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self._rows = rows

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> tuple[object, ...]:
        return self._rows


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _ScalarResult:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _ScalarResult(())
        return _ScalarResult(
            (
                SimpleNamespace(
                    semantic_model_name="qwen-test",
                    semantic_config_sha256="a" * 64,
                ),
            )
        )


def test_world_graph_config_only_reads_report_workers() -> None:
    session = _RecordingSession()

    result = asyncio.run(_live_graph_model_config(cast(AsyncSession, session)))

    assert result == ("qwen-test", "a" * 64)
    assert len(session.statements) == 2
    compiled = session.statements[1].compile()
    assert "report" in compiled.params.values()
    assert "semantic" not in compiled.params.values()
