"""核心数据模型。

整个系统围绕这些数据结构流转：
赛事(Match) -> 盘口(MarketOdds) -> 模型预测(Prediction) -> 价值评估(ValueAssessment) -> 投注建议(BetRecommendation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Outcome(str, Enum):
    """1X2（胜平负）三种结果。世界杯小组赛/淘汰赛 90 分钟赛果。"""

    HOME = "home"  # 主胜 / 体彩"3"
    DRAW = "draw"  # 平局 / 体彩"1"
    AWAY = "away"  # 客胜 / 体彩"0"


class Bookmaker(str, Enum):
    """盘口来源。"""

    SPORTTERY = "sporttery"      # 中国体彩（竞彩足球，固定赔率）
    POLYMARKET = "polymarket"    # Polymarket 预测市场（价格即隐含概率）


@dataclass
class Team:
    name: str
    fifa_rank: Optional[int] = None
    recent_form: list[str] = field(default_factory=list)  # 近期赛果，如 ["W", "W", "D", "L", "W"]
    key_injuries: list[str] = field(default_factory=list)


@dataclass
class Match:
    match_id: str
    home: Team
    away: Team
    kickoff: datetime
    stage: str = "group"  # group / round_of_16 / quarter / semi / final
    venue: Optional[str] = None
    notes: str = ""


@dataclass
class MarketOdds:
    """单一盘口对一场比赛 1X2 的报价。

    统一用 decimal odds（欧洲盘 / 十进制赔率）表示，便于跨盘口比较：
    - 体彩竞彩本身就是十进制赔率。
    - Polymarket 的价格 price∈(0,1) 通过 decimal = 1/price 归一化。
    """

    bookmaker: Bookmaker
    match_id: str
    decimal_odds: dict[Outcome, float]
    captured_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)
    """携带风控相关的盘口信号，如 {"liquidity":..,"spread":{...},"source":"slug"}。"""

    def __post_init__(self) -> None:
        for o in Outcome:
            if o not in self.decimal_odds:
                raise ValueError(f"{self.bookmaker} 盘口缺少结果 {o} 的赔率")
            if self.decimal_odds[o] <= 1.0:
                raise ValueError(f"赔率必须 > 1.0，得到 {self.decimal_odds[o]}")


@dataclass
class Prediction:
    """赛事分析智能体输出的"真实"概率估计（已归一化，和为 1）。"""

    match_id: str
    probabilities: dict[Outcome, float]
    confidence: float = 0.5  # 0~1，模型对自身估计的置信度
    rationale: str = ""

    def __post_init__(self) -> None:
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 1e-6:
            # 自动归一化，容忍智能体输出的小误差
            self.probabilities = {k: v / total for k, v in self.probabilities.items()}


@dataclass
class ValueAssessment:
    """对某一(盘口, 结果)组合的价值评估。"""

    bookmaker: Bookmaker
    outcome: Outcome
    decimal_odds: float
    model_prob: float          # 模型给出的真实概率
    implied_prob: float        # 盘口去水位后的隐含概率
    edge: float                # 期望值/单位本金 = model_prob * decimal_odds - 1
    kelly_fraction: float      # 建议下注的资金占比（已做分数凯利缩放）
    is_value: bool


@dataclass
class BetRecommendation:
    """风控后给用户的最终建议（仅推荐，不自动下注）。"""

    match_id: str
    bookmaker: Bookmaker
    outcome: Outcome
    decimal_odds: float
    stake_fraction: float       # 占总资金比例
    stake_amount: float         # 按当前 bankroll 折算的金额
    expected_value: float
    rationale: str
