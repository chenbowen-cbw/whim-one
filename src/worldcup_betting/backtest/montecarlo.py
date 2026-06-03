"""蒙特卡洛回测：无历史数据时验证下注策略的最严谨方式。

显式建模"市场如何形成"，再让策略在不知道真相的情况下博弈：

  真实概率 p_true
      │  ① 热门-冷门偏差：市场显示概率 p_disp ∝ p_true^(1/beta)  (beta>1 抬高冷门)
      ▼
  市场显示概率 p_disp
      │  ② 抽水：p_book = p_disp 归一 × overround(O>1)，赔率 = 1/p_book
      ▼
  挂出赔率  ──►  策略：去抽水 + gamma 修正估"真实" ──► 价值/凯利下注
      │  ③ 按 p_true 抽样真实结果，结算
      ▼
  统计上千场的 ROI 分布

核心结论(可复现)：当偏差强度(beta)带来的可利用 edge 超过抽水(O)时，策略长期 +EV；
否则被抽水吃掉。这诚实地界定了策略的盈利边界，而非盲目乐观。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..config import RiskConfig
from .engine import MarketSnapshot, run_backtest

_OPTS = ["home", "draw", "away"]


def _dirichlet(alpha: list[float], rng: random.Random) -> list[float]:
    g = [rng.gammavariate(a, 1.0) for a in alpha]
    s = sum(g)
    return [x / s for x in g]


def _make_snapshot(event_id: str, rng: random.Random, *, beta: float, overround: float) -> tuple[MarketSnapshot, list[float]]:
    """生成一场比赛：返回(挂盘快照, 真实概率)。"""
    # 真实概率：偏向主队的 1X2 分布
    p_true = _dirichlet([5.0, 3.0, 3.0], rng)

    # ① 热门-冷门偏差：市场显示概率（冷门被抬高）
    disp = [p ** (1.0 / beta) for p in p_true]
    s = sum(disp)
    disp = [x / s for x in disp]

    # ② 抽水：账面概率和 = overround，赔率 = 1/账面概率
    odds = {opt: 1.0 / (d * overround) for opt, d in zip(_OPTS, disp)}

    # ③ 抽样真实结果
    r = rng.random()
    cum, result = 0.0, _OPTS[-1]
    for opt, p in zip(_OPTS, p_true):
        cum += p
        if r <= cum:
            result = opt
            break

    return MarketSnapshot(event_id, odds, result), p_true


@dataclass
class MonteCarloResult:
    trials: int
    matches_per_trial: int
    beta: float
    overround: float
    gamma: float
    mean_growth: float           # 每届(trial)平均资金增长率
    median_growth: float
    prob_profit: float           # 盈利的 trial 占比
    mean_roi: float              # 每元投注平均回报
    mean_max_drawdown: float


def run_monte_carlo(
    *,
    trials: int = 500,
    matches_per_trial: int = 64,
    beta: float = 1.25,
    overround: float = 1.05,
    gamma: float = 1.20,
    cfg: RiskConfig | None = None,
    seed: int = 42,
) -> MonteCarloResult:
    """跑 trials 届、每届 matches_per_trial 场，统计资金增长与 ROI 分布。"""
    cfg = cfg or RiskConfig()
    rng = random.Random(seed)
    growths: list[float] = []
    rois: list[float] = []
    dds: list[float] = []

    for t in range(trials):
        snaps = [_make_snapshot(f"t{t}-m{i}", rng, beta=beta, overround=overround)[0]
                 for i in range(matches_per_trial)]
        m = run_backtest(snaps, cfg, gamma=gamma)
        growths.append(m.growth)
        if m.total_staked > 0:
            rois.append(m.roi)
        dds.append(m.max_drawdown)

    growths_sorted = sorted(growths)
    median = growths_sorted[len(growths_sorted) // 2] if growths_sorted else 0.0
    return MonteCarloResult(
        trials=trials,
        matches_per_trial=matches_per_trial,
        beta=beta,
        overround=overround,
        gamma=gamma,
        mean_growth=sum(growths) / len(growths) if growths else 0.0,
        median_growth=median,
        prob_profit=sum(1 for g in growths if g > 0) / len(growths) if growths else 0.0,
        mean_roi=sum(rois) / len(rois) if rois else 0.0,
        mean_max_drawdown=sum(dds) / len(dds) if dds else 0.0,
    )
