"""混合(收缩)算子 + min_market_prob 风控闸单测。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.tools.blending import blend_beliefs  # noqa: E402
from worldcup_betting.tools.outright import scan_outright_value  # noqa: E402


def test_weight_zero_equals_market():
    model = {"a": 0.6, "b": 0.4}
    market = {"a": 0.3, "b": 0.7}
    b = blend_beliefs(model, market, weight=0.0)
    assert b["a"] == pytest.approx(0.3)
    assert b["b"] == pytest.approx(0.7)


def test_weight_one_equals_model():
    model = {"a": 0.6, "b": 0.4}
    market = {"a": 0.3, "b": 0.7}
    b = blend_beliefs(model, market, weight=1.0)
    assert b["a"] == pytest.approx(0.6)
    assert b["b"] == pytest.approx(0.4)


def test_blend_between_and_normalized():
    model = {"a": 0.6, "b": 0.4}
    market = {"a": 0.3, "b": 0.7}
    b = blend_beliefs(model, market, weight=0.5)
    assert sum(b.values()) == pytest.approx(1.0)
    # a 的收缩值介于盘口与模型之间
    assert 0.3 < b["a"] < 0.6


def test_only_intersection_keys():
    b = blend_beliefs({"a": 0.5, "x": 0.5}, {"a": 1.0}, weight=0.5)
    assert set(b) == {"a"}


def test_geometric_shrinks_log_deviation():
    # 几何池：log(blend/market) = λ·log(model/market)
    import math
    model = {"a": 0.4, "b": 0.6}
    market = {"a": 0.1, "b": 0.9}
    lam = 0.3
    b = blend_beliefs(model, market, weight=lam)
    # 未归一化前的比值关系（归一化是同一常数，取两队比值消去）
    lhs = math.log(b["a"] / b["b"])
    rhs_model = math.log(model["a"] / model["b"])
    rhs_market = math.log(market["a"] / market["b"])
    assert lhs == pytest.approx(lam * rhs_model + (1 - lam) * rhs_market)


def test_invalid_weight_raises():
    with pytest.raises(ValueError):
        blend_beliefs({"a": 1.0}, {"a": 1.0}, weight=1.5)


def test_min_market_prob_gate_rejects_longshot():
    # 盘口隐含 0.5% 的极端冷门，即便有正 edge 也应被否决
    rows = [{"team": "Minnow", "raw_price": 0.005, "decimal_odds": 200.0,
             "fair_prob": 0.005, "liquidity": 1_000_000.0}]
    cfg = RiskConfig(min_market_prob=0.02)
    opps = scan_outright_value(rows, {"Minnow": 0.05}, cfg)
    assert not opps[0].is_value
    assert "冷门" in opps[0].reason


def test_min_market_prob_default_zero_keeps_behavior():
    # 默认 0 不改变既有行为：正 edge 且流动性足 → 仍是价值
    rows = [{"team": "Mid", "raw_price": 0.05, "decimal_odds": 20.0,
             "fair_prob": 0.05, "liquidity": 1_000_000.0}]
    opps = scan_outright_value(rows, {"Mid": 0.10}, RiskConfig())
    assert opps[0].is_value
