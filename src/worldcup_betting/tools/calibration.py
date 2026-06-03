"""用历史比分最大似然校准实力评分(power)。

关键：拟合的模型**与模拟器 expected_goals 完全同构**，因此拟合出的评分可直接喂进
模拟器，无缝衔接。

模型(与 tournament.expected_goals 一致)：
    λ_home = BASE * exp(SENS*(r_h - r_a)/100 + H·[非中立])
    λ_away = BASE * exp(SENS*(r_a - r_h)/100)
home_score ~ Poisson(λ_home), away_score ~ Poisson(λ_away)

对加权对数似然做梯度上升拟合 {r_t}, H。BASE/SENS 固定为模拟器常量，保证一致性。
梯度(每场，权重 w，丢弃阶乘常数)：
    g = SENS/100
    ∂ℓ/∂r_h =  w·g·[(x-λh) - (y-λa)]
    ∂ℓ/∂r_a = -∂ℓ/∂r_h
    ∂ℓ/∂H   =  w·(x-λh)        (仅非中立)
加 L2 正则把评分拉向先验 50，避免样本少的队发散；每轮中心化保证可辨识。
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

from .historical_data import HistMatch, load_matches
from .tournament import BASE_GOALS, POWER_SENSITIVITY

# 队名别名：分组用名 -> 数据集用名（其余按规范化后直接匹配）
_ALIASES = {
    "usa": "united states",
    "south korea": "south korea",
    "ivory coast": "ivory coast",
    "curacao": "curaçao",
}


def _norm(name: str) -> str:
    """规范化队名：去重音、小写、去空白，用于跨数据源匹配。"""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def dataset_name(group_team: str) -> str:
    """把分组里的队名映射到数据集队名（规范化形式）。"""
    n = _norm(group_team)
    return _norm(_ALIASES.get(n, group_team))


@dataclass
class Calibration:
    ratings: dict[str, float]   # 规范化队名 -> power
    home_adv: float
    n_matches: int
    iterations: int


def fit_ratings(
    matches: list[HistMatch] | None = None,
    *,
    iterations: int = 400,
    lr: float = 0.5,
    reg: float = 0.04,
    min_matches: float = 3.0,
    prior: float = 50.0,
) -> Calibration:
    """拟合并返回各队 power 评分（规范化队名为键）。

    reg 同时起两个作用：抑制小样本发散，并通过 数据梯度≈reg·(r-50) 的平衡点
    决定评分跨度（reg 越小跨度越大）。
    """
    matches = matches if matches is not None else load_matches()
    g = POWER_SENSITIVITY / 100.0

    # 规范化队名并统计每队权重，过滤样本过少的队
    recs = []
    wsum: dict[str, float] = {}
    for m in matches:
        h, a = _norm(m.home), _norm(m.away)
        recs.append((h, a, m.hs, m.as_, m.neutral, m.weight))
        wsum[h] = wsum.get(h, 0.0) + m.weight
        wsum[a] = wsum.get(a, 0.0) + m.weight
    teams = {t for t, w in wsum.items() if w >= min_matches}
    recs = [r for r in recs if r[0] in teams and r[1] in teams]
    total_w = sum(w for *_, w in recs) or 1.0

    r = {t: prior for t in teams}
    H = 0.25

    for _ in range(iterations):
        grad = {t: 0.0 for t in teams}
        gradH = 0.0
        for h, a, x, y, neutral, w in recs:
            lh = BASE_GOALS * math.exp(g * (r[h] - r[a]) + (0.0 if neutral else H))
            la = BASE_GOALS * math.exp(g * (r[a] - r[h]))
            dh = w * g * ((x - lh) - (y - la))
            grad[h] += dh
            grad[a] -= dh
            if not neutral:
                gradH += w * (x - lh)
        # 原始(累加)数据梯度 + L2 正则拉向先验；正则强度决定评分跨度
        for t in teams:
            r[t] += lr * (grad[t] - reg * (r[t] - prior))
        # home_adv：按总权重归一为"平均残差"，小步长 + 钳制，避免发散
        H = min(0.6, max(0.0, H + 0.5 * gradH / total_w))
        # 中心化到先验均值，保证可辨识
        shift = prior - sum(r.values()) / len(r)
        for t in teams:
            r[t] += shift

    return Calibration(ratings=r, home_adv=H, n_matches=len(recs), iterations=iterations)


def calibrated_groups(cal: Calibration, groups: dict | None = None) -> dict:
    """把分组里的 power 替换为校准值；数据集中缺失的队保留原示意值。"""
    from .wc2026_data import GROUPS

    groups = groups or GROUPS
    out: dict[str, list[tuple[str, float]]] = {}
    for grp, teams in groups.items():
        new = []
        for name, default_power in teams:
            fitted = cal.ratings.get(dataset_name(name))
            new.append((name, round(fitted, 1) if fitted is not None else default_power))
        out[grp] = new
    return out
