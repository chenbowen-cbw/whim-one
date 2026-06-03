"""期货盘(夺冠盘)价值扫描。

逻辑与逐场胜平负一致——只是把"结果"换成"哪支球队夺冠"：
  edge = 你的概率 × 赔率 − 1，  凯利 = edge / (赔率 − 1)
关键区别：单队下注，你的概率无需在全场归一（你只押你看好的几支）。

价值来自**你的判断 vs 盘口去抽水后的隐含概率**。系统不替你判断概率，
它只负责：去抽水、算 edge/凯利、用真实流动性与风控闸过滤、给金额。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import RiskConfig
from .analytics import expected_value, kelly_fraction


@dataclass
class OutrightOpportunity:
    team: str
    decimal_odds: float
    market_prob: float       # 盘口去抽水隐含概率
    user_prob: float         # 你给出的概率判断
    edge: float
    liquidity: float
    stake_fraction: float    # 受约束后的下注比例（0 表示被否决）
    stake_amount: float
    is_value: bool
    reason: str              # 价值/否决原因，便于审计


def scan_outright_value(
    rows: list[dict],
    user_beliefs: dict[str, float],
    cfg: RiskConfig,
) -> list[OutrightOpportunity]:
    """对用户给出判断的球队逐一做价值评估。

    rows: event_to_outright_probs() 的输出（含 team / fair_prob / decimal_odds / liquidity）。
    user_beliefs: {球队名: 你认为的夺冠概率}，球队名按子串匹配 rows 中的队名。
    """
    by_name = {str(r["team"]).strip().lower(): r for r in rows}

    raw: list[OutrightOpportunity] = []
    for team, p in user_beliefs.items():
        row = _lookup(by_name, team)
        if row is None:
            raw.append(_rejected(team, p, reason="盘口中未找到该队"))
            continue
        if not 0.0 < p < 1.0:
            raw.append(_rejected(team, p, row=row, reason="概率需在(0,1)"))
            continue

        d = row["decimal_odds"]
        edge = expected_value(p, d)
        liq = row["liquidity"]
        scaled = min(kelly_fraction(p, d) * cfg.kelly_scale, cfg.max_fraction_per_bet)

        # 风控闸
        if row["fair_prob"] < cfg.min_market_prob:
            reason = (f"盘口隐含 {row['fair_prob']:.2%} 低于下限 {cfg.min_market_prob:.0%}，"
                      f"极端冷门不可信(含冷门溢价)，否决")
            is_value, frac = False, 0.0
        elif liq < cfg.min_liquidity:
            reason = f"流动性 ${liq:,.0f} 低于下限 ${cfg.min_liquidity:,.0f}，防滑点否决"
            is_value, frac = False, 0.0
        elif edge < cfg.edge_threshold:
            reason = f"edge {edge:+.1%} 未达阈值 {cfg.edge_threshold:.0%}"
            is_value, frac = False, 0.0
        else:
            reason = f"你的判断 {p:.1%} > 盘口隐含 {row['fair_prob']:.1%}，正期望"
            is_value, frac = True, scaled

        raw.append(
            OutrightOpportunity(
                team=str(row["team"]),
                decimal_odds=d,
                market_prob=row["fair_prob"],
                user_prob=p,
                edge=edge,
                liquidity=liq,
                stake_fraction=frac,
                stake_amount=0.0,
                is_value=is_value,
                reason=reason,
            )
        )

    # 组合敞口上限：所有价值项合计超限则等比缩放
    total = sum(o.stake_fraction for o in raw)
    scale = cfg.max_total_exposure / total if total > cfg.max_total_exposure else 1.0
    for o in raw:
        o.stake_fraction = round(o.stake_fraction * scale, 4)
        o.stake_amount = round(o.stake_fraction * cfg.bankroll, 2)

    return sorted(raw, key=lambda o: (o.is_value, o.edge), reverse=True)


def _lookup(by_name: dict, team: str):
    low = team.strip().lower()
    if low in by_name:
        return by_name[low]
    for name, row in by_name.items():
        if low in name or name in low:
            return row
    return None


def _rejected(team: str, p: float, row=None, reason: str = "") -> OutrightOpportunity:
    return OutrightOpportunity(
        team=team,
        decimal_odds=row["decimal_odds"] if row else 0.0,
        market_prob=row["fair_prob"] if row else 0.0,
        user_prob=p,
        edge=0.0,
        liquidity=row["liquidity"] if row else 0.0,
        stake_fraction=0.0,
        stake_amount=0.0,
        is_value=False,
        reason=reason,
    )
