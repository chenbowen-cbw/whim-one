"""回测演示：历史样本回测 + 蒙特卡洛策略验证。

用法：
    python examples/backtest_demo.py            # 跑历史样本 + 蒙特卡洛
    python examples/backtest_demo.py --sweep    # 扫描不同偏差/抽水，看盈利边界

说明：2026 世界杯尚未开赛，无真实赛果。历史样本为少量"已结算"演示数据；
蒙特卡洛在无历史数据时严谨验证策略——显式建模市场偏差与抽水，看长期 ROI。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.backtest.engine import MarketSnapshot, run_backtest  # noqa: E402
from worldcup_betting.backtest.montecarlo import run_monte_carlo  # noqa: E402
from worldcup_betting.config import RiskConfig  # noqa: E402

# 演示用"已结算"赛事（赔率与结果为示意，仅用于演示引擎；非真实历史数据）
_SAMPLE = [
    MarketSnapshot("demo-1", {"home": 1.55, "draw": 3.9, "away": 6.5}, "home"),
    MarketSnapshot("demo-2", {"home": 2.40, "draw": 3.3, "away": 3.0}, "away"),
    MarketSnapshot("demo-3", {"home": 1.30, "draw": 5.2, "away": 9.0}, "home"),
    MarketSnapshot("demo-4", {"home": 4.20, "draw": 3.6, "away": 1.9}, "draw"),
    MarketSnapshot("demo-5", {"home": 1.80, "draw": 3.5, "away": 4.5}, "away"),
    MarketSnapshot("demo-6", {"home": 2.10, "draw": 3.2, "away": 3.6}, "home"),
]


def historical() -> None:
    # 演示用：放宽阈值并加大修正，使样本产生实际下注，便于展示引擎统计
    cfg = RiskConfig(edge_threshold=0.01)
    m = run_backtest(_SAMPLE, cfg, gamma=1.30)
    print("【历史样本回测】(演示数据，仅验证引擎)")
    print(f"  事件 {m.n_events}  下注 {m.n_bets}  投注额 ${m.total_staked:,.0f}")
    print(f"  盈亏 ${m.pnl:+,.0f}  ROI {m.roi:+.1%}  命中率 {m.hit_rate:.0%}")
    print(f"  资金 ${m.start_bankroll:,.0f} → ${m.final_bankroll:,.0f} "
          f"(增长 {m.growth:+.1%})  最大回撤 {m.max_drawdown:.1%}")


def montecarlo() -> None:
    r = run_monte_carlo(trials=500, matches_per_trial=64, beta=1.25, overround=1.05, gamma=1.20)
    print("\n【蒙特卡洛验证】500 届 × 64 场/届")
    print(f"  市场偏差 beta={r.beta}  抽水 {r.overround - 1:.0%}  策略修正 gamma={r.gamma}")
    print(f"  平均资金增长 {r.mean_growth:+.1%}  中位 {r.median_growth:+.1%}  "
          f"盈利届占比 {r.prob_profit:.0%}")
    print(f"  每元投注 ROI {r.mean_roi:+.1%}  平均最大回撤 {r.mean_max_drawdown:.1%}")


def sweep() -> None:
    print("\n【盈利边界扫描】固定 gamma=1.20，变化市场偏差 beta 与抽水 overround")
    print(f"  {'beta':>6}{'抽水':>8}{'平均增长':>10}{'盈利占比':>10}{'ROI':>9}")
    for beta in (1.00, 1.15, 1.25, 1.40):
        for ov in (1.03, 1.05, 1.08):
            r = run_monte_carlo(trials=300, matches_per_trial=64, beta=beta,
                                overround=ov, gamma=1.20, seed=7)
            print(f"  {beta:>6.2f}{ov - 1:>7.0%}{r.mean_growth:>+10.1%}"
                  f"{r.prob_profit:>9.0%}{r.mean_roi:>+9.1%}")
    print("  解读：beta=1.00(无偏差)→被抽水吃成负EV；偏差越强/抽水越低→越赚；")
    print("        高抽水(8%)下温和gamma多半不下注(保本0%)，正是风控该有的克制。")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sweep", action="store_true")
    args = p.parse_args()
    historical()
    montecarlo()
    if args.sweep:
        sweep()
    print("\n⚠ 回测/模拟结果不预示未来收益。真实盈利依赖你的概率优于市场，且需扣除滑点与税费。")


if __name__ == "__main__":
    main()
