"""第2步单测：对阵标题解析、逐场盘口解析、盘口基线预测。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from worldcup_betting.models import Outcome  # noqa: E402
from worldcup_betting.tools.baseline_model import market_devig_prediction  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    discover_match_odds,
    is_three_way_match,
    parse_match_title,
)


def test_parse_title_variants():
    assert parse_match_title("Argentina vs Mexico") == ("Argentina", "Mexico")
    assert parse_match_title("Argentina vs. Mexico") == ("Argentina", "Mexico")
    assert parse_match_title("Spain v Germany") == ("Spain", "Germany")
    assert parse_match_title("World Cup Winner") is None


def _three_way_event():
    return {
        "title": "Argentina vs. Mexico",
        "slug": "demo",
        "markets": [
            {"groupItemTitle": "Argentina", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0.60","0.40"]', "liquidityNum": "120000"},
            {"groupItemTitle": "Draw", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0.25","0.75"]', "liquidityNum": "80000"},
            {"groupItemTitle": "Mexico", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0.18","0.82"]', "liquidityNum": "90000"},
        ],
    }


def test_is_three_way_match():
    assert is_three_way_match(_three_way_event())
    assert not is_three_way_match({"title": "Will X happen?", "markets": []})


def test_discover_match_odds():
    odds = discover_match_odds(_three_way_event())
    assert odds is not None
    # 主胜价 0.60 -> 赔率 1/0.60
    assert odds.decimal_odds[Outcome.HOME] == pytest.approx(1 / 0.60, rel=1e-3)
    assert odds.decimal_odds[Outcome.AWAY] == pytest.approx(1 / 0.18, rel=1e-3)
    assert odds.metadata["liquidity"] == pytest.approx(290000.0)


def test_discover_non_match_returns_none():
    assert discover_match_odds({"title": "Kraken IPO?", "markets": []}) is None


def test_market_devig_prediction_sums_to_one_and_boosts_favorite():
    odds = discover_match_odds(_three_way_event())
    fair = market_devig_prediction(odds, gamma=1.0)
    boosted = market_devig_prediction(odds, gamma=1.3)
    assert sum(boosted.probabilities.values()) == pytest.approx(1.0)
    # gamma>1 抬高热门(主胜)
    assert boosted.probabilities[Outcome.HOME] > fair.probabilities[Outcome.HOME]
