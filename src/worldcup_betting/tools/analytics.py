"""赔率与资金管理的纯数学函数。

这一层完全确定性、无外部依赖、可被严格单测覆盖，是整个系统最可信赖的部分。
智能体（LLM）只负责"软"判断（估概率、读伤停消息），所有"硬"计算都落在这里。
"""

from __future__ import annotations

from ..models import (
    Bookmaker,
    MarketOdds,
    Outcome,
    Prediction,
    ValueAssessment,
)


def implied_prob(decimal_odds: float) -> float:
    """单个十进制赔率对应的隐含概率（含水位/抽水）。"""
    return 1.0 / decimal_odds


def remove_vig(decimal_odds: dict[Outcome, float]) -> dict[Outcome, float]:
    """去水位（去除博彩公司抽水），返回归一化后的隐含概率。

    用最简单的"按比例归一化"法（multiplicative / normalization）：
        p_i = (1/d_i) / Σ(1/d_j)
    Σ(1/d_j) 即 overround（>1 的部分就是庄家利润空间）。
    更精细可用 Shin / power 方法，此处保持透明可解释。
    """
    raw = {o: implied_prob(d) for o, d in decimal_odds.items()}
    overround = sum(raw.values())
    return {o: p / overround for o, p in raw.items()}


def overround(decimal_odds: dict[Outcome, float]) -> float:
    """盘口的总抽水比例（>1）。1.05 表示约 5% 的庄家优势。"""
    return sum(implied_prob(d) for d in decimal_odds.values())


def polymarket_price_to_decimal(price: float) -> float:
    """Polymarket 价格(0~1, 即份额价格/隐含概率) -> 十进制赔率。

    买入价 0.65 意味着押 1 块、赢了拿回 1/0.65 ≈ 1.538。
    """
    if not 0.0 < price < 1.0:
        raise ValueError(f"Polymarket 价格必须在 (0,1)，得到 {price}")
    return 1.0 / price


def expected_value(model_prob: float, decimal_odds: float) -> float:
    """每单位本金的期望值（即 edge）。

    EV = p * (d - 1) - (1 - p) = p * d - 1
    >0 即正期望（价值投注）。
    """
    return model_prob * decimal_odds - 1.0


def kelly_fraction(model_prob: float, decimal_odds: float) -> float:
    """完整凯利下注比例。

    f* = (b*p - q) / b,  其中 b = d - 1, q = 1 - p
    等价于 f* = (p*d - 1) / (d - 1) = EV / (d - 1)
    <=0 表示不应下注。
    """
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    f = (model_prob * decimal_odds - 1.0) / b
    return max(0.0, f)


def assess_value(
    bookmaker: Bookmaker,
    outcome: Outcome,
    decimal_odds: float,
    model_prob: float,
    implied: float,
    *,
    edge_threshold: float = 0.03,
    kelly_scale: float = 0.25,
    max_fraction: float = 0.05,
) -> ValueAssessment:
    """对单个 (盘口, 结果) 做价值评估，并产出受约束的下注比例。

    风控三道闸：
    1. edge_threshold：edge 必须超过阈值（覆盖模型误差与抽水噪声）才算价值。
    2. kelly_scale：分数凯利（默认 1/4 凯利），降低破产风险与方差。
    3. max_fraction：单注资金占比硬上限（默认 5%）。
    """
    edge = expected_value(model_prob, decimal_odds)
    raw_kelly = kelly_fraction(model_prob, decimal_odds)
    scaled = min(raw_kelly * kelly_scale, max_fraction)
    is_value = edge >= edge_threshold and scaled > 0
    return ValueAssessment(
        bookmaker=bookmaker,
        outcome=outcome,
        decimal_odds=decimal_odds,
        model_prob=model_prob,
        implied_prob=implied,
        edge=edge,
        kelly_fraction=scaled if is_value else 0.0,
        is_value=is_value,
    )


def find_value_bets(
    prediction: Prediction,
    odds_list: list[MarketOdds],
    *,
    edge_threshold: float = 0.03,
    kelly_scale: float = 0.25,
    max_fraction: float = 0.05,
) -> list[ValueAssessment]:
    """跨所有盘口、所有结果扫描价值投注。

    对每个盘口先各自去水位得到隐含概率，再与模型概率比较。
    返回按 edge 降序排列的全部评估（含非价值项，便于审计）。
    """
    assessments: list[ValueAssessment] = []
    for odds in odds_list:
        fair = remove_vig(odds.decimal_odds)
        for outcome in Outcome:
            assessments.append(
                assess_value(
                    bookmaker=odds.bookmaker,
                    outcome=outcome,
                    decimal_odds=odds.decimal_odds[outcome],
                    model_prob=prediction.probabilities[outcome],
                    implied=fair[outcome],
                    edge_threshold=edge_threshold,
                    kelly_scale=kelly_scale,
                    max_fraction=max_fraction,
                )
            )
    return sorted(assessments, key=lambda a: a.edge, reverse=True)
