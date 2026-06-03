"""夺冠盘价值扫描单测（不联网，用构造的盘口行）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.tools.outright import scan_outright_value  # noqa: E402


def _rows():
    # decimal_odds = 1/raw_price；fair_prob 为去抽水后概率（此处直接给）
    return [
        {"team": "Argentina", "raw_price": 0.085, "decimal_odds": 11.43,
         "fair_prob": 0.085, "liquidity": 1_350_000.0},
        {"team": "USA", "raw_price": 0.011, "decimal_odds": 86.96,
         "fair_prob": 0.011, "liquidity": 5_000_000.0},
        {"team": "Tinyland", "raw_price": 0.02, "decimal_odds": 50.0,
         "fair_prob": 0.02, "liquidity": 1_000.0},  # 流动性极低
    ]


def test_positive_edge_is_value():
    opps = scan_outright_value(_rows(), {"Argentina": 0.15}, RiskConfig())
    arg = next(o for o in opps if o.team == "Argentina")
    assert arg.is_value
    assert arg.edge > 0
    assert arg.stake_amount > 0


def test_negative_edge_rejected():
    # 你判断 5% < 盘口 8.5% -> 负 edge
    opps = scan_outright_value(_rows(), {"Argentina": 0.05}, RiskConfig())
    arg = next(o for o in opps if o.team == "Argentina")
    assert not arg.is_value
    assert arg.edge < 0


def test_liquidity_gate_blocks():
    # Tinyland 有正 edge 但流动性 $1k 远低于下限
    opps = scan_outright_value(_rows(), {"Tinyland": 0.10}, RiskConfig())
    t = next(o for o in opps if o.team == "Tinyland")
    assert not t.is_value
    assert "流动性" in t.reason


def test_team_not_found():
    opps = scan_outright_value(_rows(), {"Atlantis": 0.10}, RiskConfig())
    assert opps[0].reason == "盘口中未找到该队"


def test_total_exposure_cap():
    cfg = RiskConfig(max_total_exposure=0.05, max_fraction_per_bet=0.05)
    beliefs = {"Argentina": 0.20, "USA": 0.05}  # 两个都强正 edge
    opps = scan_outright_value(_rows(), beliefs, cfg)
    total = sum(o.stake_fraction for o in opps if o.is_value)
    assert total <= cfg.max_total_exposure + 1e-9


def test_substring_match():
    opps = scan_outright_value(_rows(), {"argentina": 0.15}, RiskConfig())
    assert opps[0].team == "Argentina"
