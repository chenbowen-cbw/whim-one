"""确定性内核单测：赔率换算、去水位、EV、凯利、价值扫描、风控。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.models import Bookmaker, MarketOdds, Outcome, Prediction  # noqa: E402
from worldcup_betting.risk import build_recommendations  # noqa: E402
from worldcup_betting.tools.analytics import (  # noqa: E402
    expected_value,
    find_value_bets,
    implied_prob,
    kelly_fraction,
    overround,
    polymarket_price_to_decimal,
    remove_vig,
)


def test_implied_prob():
    assert implied_prob(2.0) == pytest.approx(0.5)
    assert implied_prob(4.0) == pytest.approx(0.25)


def test_remove_vig_sums_to_one():
    odds = {Outcome.HOME: 1.55, Outcome.DRAW: 3.90, Outcome.AWAY: 6.50}
    fair = remove_vig(odds)
    assert sum(fair.values()) == pytest.approx(1.0)
    # 去水位后概率应小于含水位的原始隐含概率
    assert fair[Outcome.HOME] < implied_prob(1.55)


def test_overround_above_one():
    odds = {Outcome.HOME: 1.55, Outcome.DRAW: 3.90, Outcome.AWAY: 6.50}
    assert overround(odds) > 1.0


def test_polymarket_conversion():
    assert polymarket_price_to_decimal(0.5) == pytest.approx(2.0)
    assert polymarket_price_to_decimal(0.25) == pytest.approx(4.0)
    with pytest.raises(ValueError):
        polymarket_price_to_decimal(1.5)


def test_expected_value_sign():
    # 真实概率 60%，赔率 2.0 -> EV = 0.2 (正期望)
    assert expected_value(0.6, 2.0) == pytest.approx(0.2)
    # 真实概率 40%，赔率 2.0 -> EV = -0.2 (负期望)
    assert expected_value(0.4, 2.0) == pytest.approx(-0.2)


def test_kelly_fraction():
    # p=0.6, d=2.0 -> f = (0.6*2-1)/(2-1) = 0.2
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)
    # 负期望返回 0
    assert kelly_fraction(0.4, 2.0) == 0.0


def test_find_value_bets_detects_edge():
    # 模型认为主胜 70%，盘口给 2.0（隐含约50%）-> 明显价值
    pred = Prediction(
        match_id="M",
        probabilities={Outcome.HOME: 0.70, Outcome.DRAW: 0.20, Outcome.AWAY: 0.10},
    )
    odds = MarketOdds(
        bookmaker=Bookmaker.SPORTTERY,
        match_id="M",
        decimal_odds={Outcome.HOME: 2.0, Outcome.DRAW: 3.5, Outcome.AWAY: 8.0},
    )
    results = find_value_bets(pred, [odds])
    home = next(a for a in results if a.outcome == Outcome.HOME)
    assert home.is_value
    assert home.edge > 0
    assert home.kelly_fraction > 0


def test_risk_confidence_gate_blocks():
    pred = Prediction(
        match_id="M",
        probabilities={Outcome.HOME: 0.70, Outcome.DRAW: 0.20, Outcome.AWAY: 0.10},
        confidence=0.1,  # 低于默认 min_confidence
    )
    odds = MarketOdds(
        bookmaker=Bookmaker.SPORTTERY,
        match_id="M",
        decimal_odds={Outcome.HOME: 2.0, Outcome.DRAW: 3.5, Outcome.AWAY: 8.0},
    )
    assessments = find_value_bets(pred, [odds])
    recs = build_recommendations(pred, assessments, RiskConfig())
    assert recs == []


def test_risk_total_exposure_cap():
    cfg = RiskConfig(max_total_exposure=0.10, max_fraction_per_bet=0.08)
    pred = Prediction(
        match_id="M",
        probabilities={Outcome.HOME: 0.55, Outcome.DRAW: 0.30, Outcome.AWAY: 0.15},
        confidence=0.9,
    )
    # 两个盘口都对主胜给出高赔率，制造多个价值项
    odds = [
        MarketOdds(Bookmaker.SPORTTERY, "M",
                   {Outcome.HOME: 2.4, Outcome.DRAW: 3.5, Outcome.AWAY: 6.0}),
        MarketOdds(Bookmaker.POLYMARKET, "M",
                   {Outcome.HOME: 2.5, Outcome.DRAW: 3.6, Outcome.AWAY: 6.2}),
    ]
    assessments = find_value_bets(pred, odds)
    recs = build_recommendations(pred, assessments, cfg)
    total = sum(r.stake_fraction for r in recs)
    assert total <= cfg.max_total_exposure + 1e-9
