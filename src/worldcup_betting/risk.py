"""风控与资金管理智能体的确定性内核。

把价值评估(ValueAssessment)转化为最终投注建议(BetRecommendation)，并施加组合级约束：
- 置信度闸门：模型置信度过低则全部否决。
- 单注上限：assess_value 已处理，这里再兜底。
- 组合敞口上限：一场比赛所有建议合计不超过 max_total_exposure，超出则按比例缩放。
"""

from __future__ import annotations

from .config import RiskConfig
from .models import BetRecommendation, Prediction, ValueAssessment


def build_recommendations(
    prediction: Prediction,
    assessments: list[ValueAssessment],
    cfg: RiskConfig,
) -> list[BetRecommendation]:
    # 1. 置信度闸门
    if prediction.confidence < cfg.min_confidence:
        return []

    # 2. 只保留价值项，并施加单注上限
    value_items = [a for a in assessments if a.is_value]
    for a in value_items:
        a.kelly_fraction = min(a.kelly_fraction, cfg.max_fraction_per_bet)

    # 3. 组合敞口上限：合计超限则等比缩放
    total = sum(a.kelly_fraction for a in value_items)
    scale = 1.0
    if total > cfg.max_total_exposure and total > 0:
        scale = cfg.max_total_exposure / total

    recs: list[BetRecommendation] = []
    for a in value_items:
        frac = a.kelly_fraction * scale
        if frac <= 0:
            continue
        recs.append(
            BetRecommendation(
                match_id=prediction.match_id,
                bookmaker=a.bookmaker,
                outcome=a.outcome,
                decimal_odds=a.decimal_odds,
                stake_fraction=frac,
                stake_amount=round(frac * cfg.bankroll, 2),
                expected_value=a.edge,
                rationale=(
                    f"模型概率 {a.model_prob:.1%} > 盘口隐含 {a.implied_prob:.1%}，"
                    f"edge {a.edge:+.1%}，分数凯利建议 {frac:.1%} 资金。"
                ),
            )
        )
    return sorted(recs, key=lambda r: r.expected_value, reverse=True)
