"""回归测试：code review 发现的 0/1 越界价格与共享对象修改问题。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.models import Bookmaker, MarketOdds, Outcome, Prediction  # noqa: E402
from worldcup_betting.risk import build_recommendations  # noqa: E402
from worldcup_betting.tools.analytics import find_value_bets  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketError,
    discover_match_odds,
    event_to_outright_probs,
)


def _binary_market(label, yes_price, liq="100000"):
    return {
        "groupItemTitle": label,
        "outcomes": '["Yes","No"]',
        "outcomePrices": f'["{yes_price}","{1 - yes_price}"]',
        "liquidityNum": liq,
    }


# --- 发现1：逐场极端价格不应崩溃，应优雅返回 None ---
def test_discover_match_extreme_zero_price_returns_none():
    ev = {
        "title": "Brazil vs. Tinyland",
        "slug": "demo",
        "markets": [
            _binary_market("Brazil", 0.97),
            _binary_market("Draw", 0.03),
            {"groupItemTitle": "Tinyland", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0","1"]', "liquidityNum": "90000"},
        ],
    }
    assert discover_match_odds(ev) is None  # 不抛 ValueError


def test_discover_match_normal_still_works():
    ev = {
        "title": "Argentina vs. Mexico",
        "slug": "ok",
        "markets": [
            _binary_market("Argentina", 0.60),
            _binary_market("Draw", 0.25),
            _binary_market("Mexico", 0.18),
        ],
    }
    odds = discover_match_odds(ev)
    assert odds is not None
    assert odds.decimal_odds[Outcome.HOME] > 1.0


# --- 发现2：夺冠盘 Yes 价为 1.0 应跳过该队而非崩溃 ---
def test_outright_skips_price_one():
    ev = {"slug": "x", "markets": [
        _binary_market("Sure", 1.0),       # 越界，应跳过
        _binary_market("France", 0.17),
        _binary_market("Spain", 0.16),
    ]}
    rows = event_to_outright_probs(ev)  # 不抛 ValueError
    teams = {r["team"] for r in rows}
    assert "Sure" not in teams
    assert {"France", "Spain"} <= teams


# --- 发现3：build_recommendations 不得修改传入的 ValueAssessment ---
def test_recommendations_do_not_mutate_assessments():
    pred = Prediction(
        match_id="M",
        probabilities={Outcome.HOME: 0.70, Outcome.DRAW: 0.20, Outcome.AWAY: 0.10},
        confidence=0.9,
    )
    odds = MarketOdds(
        bookmaker=Bookmaker.SPORTTERY,
        match_id="M",
        decimal_odds={Outcome.HOME: 2.0, Outcome.DRAW: 3.5, Outcome.AWAY: 8.0},
    )
    assessments = find_value_bets(pred, [odds], max_fraction=1.0)  # 不在扫描阶段截断
    home = next(a for a in assessments if a.outcome == Outcome.HOME and a.is_value)
    raw_kelly = home.kelly_fraction
    assert raw_kelly > 0.05  # 原始凯利大于单注上限，确保截断会改变值

    cfg = RiskConfig(max_fraction_per_bet=0.05)
    build_recommendations(pred, assessments, cfg)
    # 原始 assessment 的 kelly_fraction 未被覆盖
    assert home.kelly_fraction == raw_kelly
