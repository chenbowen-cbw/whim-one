"""赛事数据源。

定义统一接口 MatchDataProvider，并给出 MockMatchDataProvider 便于离线跑通。
接真实数据时，新增一个实现（如 API-Football / FotMob 抓取）即可，无需改动上层。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Match, Team


class MatchDataProvider(ABC):
    """赛事/球队数据提供方接口。"""

    @abstractmethod
    def get_match(self, match_id: str) -> Match: ...

    @abstractmethod
    def list_upcoming(self) -> list[Match]: ...


_MOCK_MATCHES: dict[str, Match] = {
    "WC2026-G-ARG-MEX": Match(
        match_id="WC2026-G-ARG-MEX",
        home=Team(
            name="阿根廷",
            fifa_rank=1,
            recent_form=["W", "W", "W", "D", "W"],
            key_injuries=[],
        ),
        away=Team(
            name="墨西哥",
            fifa_rank=14,
            recent_form=["W", "L", "D", "W", "L"],
            key_injuries=["主力中卫停赛"],
        ),
        kickoff=datetime(2026, 6, 20, 3, 0),
        stage="group",
        venue="MetLife Stadium",
        notes="卫冕冠军 vs 传统强队，阿根廷整体实力占优。",
    ),
}


class MockMatchDataProvider(MatchDataProvider):
    """内置示例数据，无需网络即可演示完整流程。"""

    def get_match(self, match_id: str) -> Match:
        if match_id not in _MOCK_MATCHES:
            raise KeyError(f"未找到比赛 {match_id}")
        return _MOCK_MATCHES[match_id]

    def list_upcoming(self) -> list[Match]:
        return list(_MOCK_MATCHES.values())
