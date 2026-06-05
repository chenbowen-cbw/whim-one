"""多盘口扫描相关：多结果模拟、独立收缩、盘口分类、跨盘口扫描。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.tools.blending import blend_independent  # noqa: E402
from worldcup_betting.tools.market_scan import classify_event, scan_world_cup  # noqa: E402
from worldcup_betting.tools.tournament import (  # noqa: E402
    team_groups,
    tournament_probabilities,
)
from worldcup_betting.tools.wc2026_data import GROUPS  # noqa: E402


def test_tournament_probabilities_sums():
    p = tournament_probabilities(GROUPS, n_sims=1500, seed=1)
    s = lambda d: sum(d.values())  # noqa: E731
    assert s(p["champion"]) == pytest.approx(1.0, abs=1e-6)
    assert s(p["group_winner"]) == pytest.approx(12.0, abs=1e-6)   # 每组一个头名
    assert s(p["reach_r16"]) == pytest.approx(16.0, abs=1e-6)
    assert s(p["reach_qf"]) == pytest.approx(8.0, abs=1e-6)
    assert s(p["reach_sf"]) == pytest.approx(4.0, abs=1e-6)


def test_stage_monotonicity_per_team():
    p = tournament_probabilities(GROUPS, n_sims=1500, seed=2)
    for t in p["champion"]:
        assert p["reach_r16"][t] >= p["reach_qf"][t] >= p["reach_sf"][t] \
            >= p["reach_final"][t] >= p["champion"][t]


def test_team_groups_mapping():
    tg = team_groups(GROUPS)
    assert tg["Spain"] == "D"
    assert len(tg) == 48


def test_classify_event():
    assert classify_event("World Cup Winner ")[0] == "champion"
    assert classify_event("World Cup Group D Winner")[:2] == ("group_winner", "D")
    assert classify_event("World Cup: Nation To Reach Round of 16")[0] == "reach_r16"
    assert classify_event("World Cup: Nation To Reach Quarterfinals")[0] == "reach_qf"
    assert classify_event("World Cup: Golden Boot Winner") is None


def test_blend_independent_endpoints_and_no_renorm():
    model = {"a": 0.4, "b": 0.5}
    market = {"a": 0.1, "b": 0.2}
    assert blend_independent(model, market, weight=0.0)["a"] == pytest.approx(0.1)
    assert blend_independent(model, market, weight=1.0)["a"] == pytest.approx(0.4)
    # 独立：不跨键归一，各键介于两者之间
    b = blend_independent(model, market, weight=0.5)
    assert 0.1 < b["a"] < 0.4 and 0.2 < b["b"] < 0.5
    assert sum(b.values()) != pytest.approx(1.0)  # 不强制和为1


def _binary(team, yes):
    return {"groupItemTitle": team, "outcomes": '["Yes","No"]',
            "outcomePrices": f'["{yes}","{1-yes}"]', "liquidityNum": "1000000"}


def test_scan_finds_value_when_model_beats_market():
    # 夺冠盘：市场给 TeamA 10%，模型给 35% → 收缩后仍有正 edge
    champ = {"title": "World Cup Winner",
             "markets": [_binary("TeamA", 0.10), _binary("TeamB", 0.25), _binary("TeamC", 0.65)]}
    probs = {"champion": {"TeamA": 0.35, "TeamB": 0.25, "TeamC": 0.40},
             "group_winner": {}, "reach_r16": {}, "reach_qf": {}, "reach_sf": {}, "reach_final": {}}
    bets = scan_world_cup([champ], probs, {}, weight=0.5,
                          cfg=RiskConfig(bankroll=1000, min_market_prob=0.02))
    teams = {b.team for b in bets}
    assert "TeamA" in teams
    a = next(b for b in bets if b.team == "TeamA")
    assert a.market == "夺冠" and a.edge > 0 and a.stake_amount > 0


def test_scan_empty_when_model_matches_market():
    champ = {"title": "World Cup Winner",
             "markets": [_binary("TeamA", 0.30), _binary("TeamB", 0.30), _binary("TeamC", 0.40)]}
    probs = {"champion": {"TeamA": 0.30, "TeamB": 0.30, "TeamC": 0.40},
             "group_winner": {}, "reach_r16": {}, "reach_qf": {}, "reach_sf": {}, "reach_final": {}}
    bets = scan_world_cup([champ], probs, {}, weight=0.5, cfg=RiskConfig(min_market_prob=0.02))
    assert bets == []
