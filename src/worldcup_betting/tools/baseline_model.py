"""确定性基线赛果预测器。

作用有二：
1. 无 ANTHROPIC_API_KEY 时，让整条流水线仍能端到端跑通。
2. 作为 LLM 分析智能体的"对照基准"——智能体的概率若大幅偏离基线，应给出理由。

方法：用 FIFA 排名差 + 近期状态打一个简单的实力分，再映射到胜平负概率。
刻意保持简单透明；真实场景应替换为 Elo / Dixon-Coles / xG 等模型。
"""

from __future__ import annotations

import math

from ..models import Match, MarketOdds, Outcome, Prediction
from .analytics import remove_vig

_FORM_POINTS = {"W": 3.0, "D": 1.0, "L": 0.0}


def _form_score(form: list[str]) -> float:
    """近期状态得分，0~1。"""
    if not form:
        return 0.5
    pts = sum(_FORM_POINTS.get(r, 1.0) for r in form)
    return pts / (3.0 * len(form))


def _rank_strength(rank: int | None) -> float:
    """FIFA 排名 -> 实力分。排名越靠前分越高，用对数压缩差距。"""
    r = rank if rank and rank > 0 else 50
    return 1.0 / math.log2(r + 2)


def baseline_predict(match: Match, *, home_advantage: float = 0.15) -> Prediction:
    """产出胜平负概率。

    思路：主客各算一个实力分（实力 + 状态 + 主场加成），用 softmax 拉开主客胜，
    平局概率随双方实力接近而升高。
    """
    home_str = _rank_strength(match.home.fifa_rank) + 0.3 * _form_score(match.home.recent_form)
    away_str = _rank_strength(match.away.fifa_rank) + 0.3 * _form_score(match.away.recent_form)
    home_str += home_advantage  # 主场/中立场微调

    diff = home_str - away_str
    # 主客胜的相对权重（温度刻意偏保守，避免基线过度自信）
    w_home = math.exp(1.4 * diff)
    w_away = math.exp(-1.4 * diff)
    # 实力越接近，平局权重越大
    w_draw = math.exp(-2.0 * abs(diff)) * 1.5

    total = w_home + w_draw + w_away
    probs = {
        Outcome.HOME: w_home / total,
        Outcome.DRAW: w_draw / total,
        Outcome.AWAY: w_away / total,
    }
    return Prediction(
        match_id=match.match_id,
        probabilities=probs,
        confidence=0.45,  # 基线模型置信度刻意偏低
        rationale=(
            f"基线模型：{match.home.name}(rank {match.home.fifa_rank}) vs "
            f"{match.away.name}(rank {match.away.fifa_rank})，"
            f"含主场加成 {home_advantage}。"
        ),
    )


def market_devig_prediction(odds: MarketOdds, *, gamma: float = 1.10) -> Prediction:
    """仅凭盘口得出 1X2 基线预测：去抽水 + 热门-冷门偏差修正(p∝p^gamma)。

    适用于没有球队基本面数据的真实比赛——直接用市场自身估"真实"概率。
    gamma=1.0 即等于市场(零观点)；>1 抬高热门、压低冷门。
    """
    fair = remove_vig(odds.decimal_odds)
    powered = {o: max(p, 1e-9) ** gamma for o, p in fair.items()}
    total = sum(powered.values())
    probs = {o: powered[o] / total for o in Outcome}
    return Prediction(
        match_id=odds.match_id,
        probabilities=probs,
        confidence=0.45,
        rationale=f"盘口基线：去抽水后做热门-冷门修正(gamma={gamma})。",
    )
