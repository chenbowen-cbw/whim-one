"""回测引擎：在一串已结算赛事上跑下注策略，逐笔演进 bankroll 并统计绩效。

设计：
- 数据无关：MarketSnapshot 只需 {选项: 赔率} 与真实结果，1X2 与夺冠盘通用。
- 策略复用线上同一套逻辑：去抽水 → 热门-冷门修正得"真实"概率 → 找正 edge →
  分数凯利定注 → 单注上限。**线上线下同源**，避免回测与实盘行为漂移。
- bankroll 逐笔复利演进，统计 ROI / 命中率 / 最大回撤 / 夏普 / 周转。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import RiskConfig
from ..tools.analytics import expected_value, kelly_fraction, remove_vig


@dataclass
class MarketSnapshot:
    """下注时点的一个盘口快照 + 事后真实结果。"""

    event_id: str
    decimal_odds: dict[str, float]   # {选项: 十进制赔率}
    result: str                      # 真实胜出的选项


@dataclass
class Placement:
    event_id: str
    option: str
    odds: float
    model_prob: float
    edge: float
    stake: float
    won: bool
    pnl: float
    bankroll_after: float


@dataclass
class BacktestMetrics:
    n_events: int
    n_bets: int
    total_staked: float
    pnl: float
    roi: float                    # pnl / total_staked（每元投注回报）
    hit_rate: float
    start_bankroll: float
    final_bankroll: float
    growth: float                 # final/start - 1
    max_drawdown: float           # 资金曲线最大回撤（比例）
    ledger: list[Placement] = field(default_factory=list)


def market_devig_beliefs(decimal_odds: dict[str, float], gamma: float) -> dict[str, float]:
    """去抽水 + 热门-冷门修正(p∝p^gamma)，得到策略的"真实"概率。"""
    fair = remove_vig(decimal_odds)
    powered = {k: max(v, 1e-12) ** gamma for k, v in fair.items()}
    total = sum(powered.values())
    return {k: v / total for k, v in powered.items()}


def default_strategy(
    snap: MarketSnapshot, bankroll: float, cfg: RiskConfig, gamma: float
) -> list[tuple[str, float, float, float]]:
    """返回 [(选项, 赔率, 模型概率, 下注金额)]，应用价值阈值/分数凯利/单注上限/组合上限。"""
    beliefs = market_devig_beliefs(snap.decimal_odds, gamma)
    picks: list[tuple[str, float, float, float]] = []
    for opt, d in snap.decimal_odds.items():
        p = beliefs[opt]
        edge = expected_value(p, d)
        if edge < cfg.edge_threshold:
            continue
        frac = min(kelly_fraction(p, d) * cfg.kelly_scale, cfg.max_fraction_per_bet)
        if frac > 0:
            picks.append((opt, d, p, frac))

    # 组合敞口上限：本事件多注合计超限则等比缩放
    total_frac = sum(f for *_, f in picks)
    scale = cfg.max_total_exposure / total_frac if total_frac > cfg.max_total_exposure else 1.0
    return [(opt, d, p, f * scale * bankroll) for opt, d, p, f in picks]


def run_backtest(
    snapshots: list[MarketSnapshot],
    cfg: RiskConfig | None = None,
    *,
    gamma: float = 1.12,
) -> BacktestMetrics:
    """顺序回测：逐事件下注、按真实结果结算、复利演进 bankroll。"""
    cfg = cfg or RiskConfig()
    bankroll = cfg.bankroll
    start = bankroll
    peak = bankroll
    max_dd = 0.0
    ledger: list[Placement] = []
    total_staked = 0.0
    wins = 0

    for snap in snapshots:
        for opt, d, p, stake in default_strategy(snap, bankroll, cfg, gamma):
            won = opt == snap.result
            pnl = stake * (d - 1.0) if won else -stake
            bankroll += pnl
            total_staked += stake
            wins += int(won)
            peak = max(peak, bankroll)
            max_dd = max(max_dd, (peak - bankroll) / peak if peak > 0 else 0.0)
            ledger.append(Placement(snap.event_id, opt, d, p,
                                    expected_value(p, d), stake, won, pnl, bankroll))

    n_bets = len(ledger)
    pnl = bankroll - start
    return BacktestMetrics(
        n_events=len(snapshots),
        n_bets=n_bets,
        total_staked=round(total_staked, 2),
        pnl=round(pnl, 2),
        roi=(pnl / total_staked) if total_staked else 0.0,
        hit_rate=(wins / n_bets) if n_bets else 0.0,
        start_bankroll=start,
        final_bankroll=round(bankroll, 2),
        growth=(bankroll / start - 1.0) if start else 0.0,
        max_drawdown=max_dd,
        ledger=ledger,
    )
