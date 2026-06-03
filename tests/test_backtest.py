"""第3步单测：回测引擎 + 蒙特卡洛（seed 固定，确定性）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.backtest.engine import (  # noqa: E402
    MarketSnapshot,
    market_devig_beliefs,
    run_backtest,
)
from worldcup_betting.backtest.montecarlo import run_monte_carlo  # noqa: E402
from worldcup_betting.config import RiskConfig  # noqa: E402


def test_devig_beliefs_sum_to_one():
    b = market_devig_beliefs({"home": 1.55, "draw": 3.9, "away": 6.5}, gamma=1.2)
    assert abs(sum(b.values()) - 1.0) < 1e-9
    assert b["home"] > b["away"]


def test_backtest_winning_bet_grows_bankroll():
    # 强热门、低赔率，gamma 放大后产生价值，且结果为主胜 → 应盈利
    snaps = [MarketSnapshot("e1", {"home": 1.50, "draw": 4.5, "away": 7.0}, "home")]
    m = run_backtest(snaps, RiskConfig(edge_threshold=0.005), gamma=1.4)
    assert m.n_bets >= 1
    assert m.final_bankroll > m.start_bankroll
    assert m.pnl > 0


def test_backtest_no_value_no_bets():
    # gamma=1.0 即等于市场，去抽水后无 edge → 不下注
    snaps = [MarketSnapshot("e1", {"home": 2.0, "draw": 3.5, "away": 4.0}, "home")]
    m = run_backtest(snaps, RiskConfig(), gamma=1.0)
    assert m.n_bets == 0
    assert m.final_bankroll == m.start_bankroll


def test_backtest_metrics_consistency():
    snaps = [
        MarketSnapshot("e1", {"home": 1.5, "draw": 4.5, "away": 7.0}, "home"),
        MarketSnapshot("e2", {"home": 1.6, "draw": 4.0, "away": 6.0}, "away"),
    ]
    m = run_backtest(snaps, RiskConfig(edge_threshold=0.005), gamma=1.4)
    # 末资金 = 起始 + 盈亏；命中率在 [0,1]
    assert abs(m.final_bankroll - (m.start_bankroll + m.pnl)) < 1e-6
    assert 0.0 <= m.hit_rate <= 1.0
    assert m.n_bets == len(m.ledger)


def test_monte_carlo_no_bias_not_better_than_bias():
    # 无偏差(beta=1) 的长期增长应劣于强偏差(beta=1.4) —— 价值确实来自偏差
    no_bias = run_monte_carlo(trials=200, matches_per_trial=64, beta=1.0,
                              overround=1.05, gamma=1.20, seed=1)
    strong = run_monte_carlo(trials=200, matches_per_trial=64, beta=1.4,
                             overround=1.05, gamma=1.20, seed=1)
    assert strong.mean_growth > no_bias.mean_growth


def test_monte_carlo_strong_bias_profitable():
    r = run_monte_carlo(trials=300, matches_per_trial=64, beta=1.4,
                        overround=1.03, gamma=1.25, seed=3)
    assert r.mean_growth > 0
    assert r.prob_profit > 0.5
