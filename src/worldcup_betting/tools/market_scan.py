"""实时扫描 Polymarket 上**所有可建模的**世界杯盘口，给出价值投注。

不止夺冠盘——把同一次赛制模拟产出的多种概率，分别对上对应的 Polymarket 盘口：

  夺冠(champion)          ← "World Cup Winner"
  小组头名(group_winner)  ← "World Cup Group X Winner"
  进16强(reach_r16)       ← "Nation To Reach Round of 16"
  进8强(reach_qf)         ← "Nation To Reach Quarterfinals"
  进4强(reach_sf)         ← "Nation To Reach Semifinals"

互斥盘口(夺冠/小组头名，和≈1)用归一化几何收缩；独立盘口(进各轮，各队独立)用 logit 收缩。
算不出模型概率的盘口(金球/金靴/洲别/球员 H2H 等)不在此扫描——诚实地不给无依据的建议。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import RiskConfig
from .blending import blend_beliefs, blend_independent
from .calibration import dataset_name
from .outright import scan_outright_value
from .polymarket import PolymarketError, event_to_outright_probs

# (结果类型, 是否互斥, 中文标签)
_EXCLUSIVE = "exclusive"
_INDEPENDENT = "independent"


def classify_event(title: str) -> tuple[str, str | None, str, str] | None:
    """把盘口标题归类到模型结果类型。返回 (kind, group, mode, 中文标签) 或 None。"""
    t = (title or "").strip().lower()
    if t == "world cup winner":
        return ("champion", None, _EXCLUSIVE, "夺冠")
    m = re.match(r"world cup group ([a-l]) winner", t)
    if m:
        g = m.group(1).upper()
        return ("group_winner", g, _EXCLUSIVE, f"{g}组头名")
    if "reach round of 16" in t:
        return ("reach_r16", None, _INDEPENDENT, "进16强")
    if "reach quarterfinals" in t:
        return ("reach_qf", None, _INDEPENDENT, "进8强")
    if "reach semifinals" in t:
        return ("reach_sf", None, _INDEPENDENT, "进4强")
    return None


@dataclass
class ScanBet:
    market: str          # 中文盘口标签
    kind: str
    team: str            # 原始(英文)队名
    decimal_odds: float
    model_prob: float
    market_prob: float
    blended_prob: float
    edge: float
    stake_fraction: float
    stake_amount: float


def scan_world_cup(
    events: list[dict],
    model_probs: dict[str, dict[str, float]],
    team_grp: dict[str, str],
    *,
    weight: float = 0.35,
    cfg: RiskConfig | None = None,
) -> list[ScanBet]:
    """扫描所有可建模盘口，返回通过风控的价值投注(按 edge 降序)。"""
    cfg = cfg or RiskConfig(min_market_prob=0.02)
    out: list[ScanBet] = []

    for ev in events:
        cl = classify_event(ev.get("title", ""))
        if not cl:
            continue
        kind, group, mode, label = cl
        try:
            rows = event_to_outright_probs(ev)
        except PolymarketError:
            continue
        if not rows:
            continue

        mp = model_probs.get(kind, {})
        if group:  # 小组头名：模型概率只取该组球队
            model = {dataset_name(t): p for t, p in mp.items() if team_grp.get(t) == group}
        else:
            model = {dataset_name(t): p for t, p in mp.items()}
        market = {dataset_name(str(r["team"])): r["fair_prob"] for r in rows}

        if mode == _EXCLUSIVE:
            blended = blend_beliefs(model, market, weight=weight)
        else:
            blended = blend_independent(model, market, weight=weight)

        norm_to_team = {dataset_name(str(r["team"])): str(r["team"]) for r in rows}
        beliefs = {norm_to_team[k]: v for k, v in blended.items() if k in norm_to_team}
        if not beliefs:
            continue

        for o in scan_outright_value(rows, beliefs, cfg):
            if o.is_value:
                out.append(ScanBet(
                    market=label, kind=kind, team=o.team, decimal_odds=o.decimal_odds,
                    model_prob=model.get(dataset_name(o.team), 0.0),
                    market_prob=o.market_prob, blended_prob=o.user_prob, edge=o.edge,
                    stake_fraction=o.stake_fraction, stake_amount=o.stake_amount,
                ))

    # 全局组合敞口上限：跨所有盘口合计超限则等比缩放
    total = sum(b.stake_fraction for b in out)
    if total > cfg.max_total_exposure and total > 0:
        scale = cfg.max_total_exposure / total
        for b in out:
            b.stake_fraction = round(b.stake_fraction * scale, 4)
            b.stake_amount = round(b.stake_amount * scale, 2)

    return sorted(out, key=lambda b: b.edge, reverse=True)
