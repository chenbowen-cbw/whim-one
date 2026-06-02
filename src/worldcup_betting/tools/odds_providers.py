"""盘口数据源：体彩 + Polymarket。

统一输出 MarketOdds（十进制赔率）。Polymarket 价格在此转换为十进制赔率，
使下游价值评估对所有盘口"一视同仁"。

接真实数据时：
- 体彩：竞彩足球可解析官方/聚合站的胜平负固定赔率。
- Polymarket：通过其 CLOB / Gamma API 读取对应市场的 outcome 价格。
两者都各自实现 OddsProvider 即可。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Bookmaker, MarketOdds, Outcome
from .analytics import polymarket_price_to_decimal


class OddsProvider(ABC):
    @property
    @abstractmethod
    def bookmaker(self) -> Bookmaker: ...

    @abstractmethod
    def get_odds(self, match_id: str) -> MarketOdds: ...


# --- 体彩（竞彩足球，固定十进制赔率） ---
_MOCK_SPORTTERY: dict[str, dict[Outcome, float]] = {
    "WC2026-G-ARG-MEX": {Outcome.HOME: 1.55, Outcome.DRAW: 3.90, Outcome.AWAY: 6.50},
}


class MockSportteryProvider(OddsProvider):
    @property
    def bookmaker(self) -> Bookmaker:
        return Bookmaker.SPORTTERY

    def get_odds(self, match_id: str) -> MarketOdds:
        if match_id not in _MOCK_SPORTTERY:
            raise KeyError(f"体彩无 {match_id} 盘口")
        return MarketOdds(
            bookmaker=Bookmaker.SPORTTERY,
            match_id=match_id,
            decimal_odds=dict(_MOCK_SPORTTERY[match_id]),
        )


# --- Polymarket（价格即隐含概率，0~1） ---
# 例：主胜 0.60、平 0.24、客胜 0.13（和略小于1，因含点差/流动性）
_MOCK_POLYMARKET_PRICES: dict[str, dict[Outcome, float]] = {
    "WC2026-G-ARG-MEX": {Outcome.HOME: 0.60, Outcome.DRAW: 0.24, Outcome.AWAY: 0.13},
}


class MockPolymarketProvider(OddsProvider):
    @property
    def bookmaker(self) -> Bookmaker:
        return Bookmaker.POLYMARKET

    def get_odds(self, match_id: str) -> MarketOdds:
        if match_id not in _MOCK_POLYMARKET_PRICES:
            raise KeyError(f"Polymarket 无 {match_id} 市场")
        prices = _MOCK_POLYMARKET_PRICES[match_id]
        decimal = {o: polymarket_price_to_decimal(p) for o, p in prices.items()}
        return MarketOdds(
            bookmaker=Bookmaker.POLYMARKET,
            match_id=match_id,
            decimal_odds=decimal,
        )


def all_mock_providers() -> list[OddsProvider]:
    return [MockSportteryProvider(), MockPolymarketProvider()]
