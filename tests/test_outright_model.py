"""第1步单测：热门-冷门偏差基线 + LLM beliefs 解析。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.agents.outright_analyst import _extract_beliefs  # noqa: E402
from worldcup_betting.tools.outright_model import favorite_longshot_beliefs  # noqa: E402


def _rows():
    return [
        {"team": "France", "fair_prob": 0.166},
        {"team": "Spain", "fair_prob": 0.159},
        {"team": "Norway", "fair_prob": 0.027},
        {"team": "Belgium", "fair_prob": 0.019},
    ]


def test_gamma_one_equals_market():
    b = favorite_longshot_beliefs(_rows(), gamma=1.0)
    # gamma=1 时只是归一化，相对大小与市场一致；和为1
    assert abs(sum(b.values()) - 1.0) < 1e-9
    assert b["France"] > b["Belgium"]


def test_gamma_boosts_favorites():
    market = {r["team"]: r["fair_prob"] for r in _rows()}
    msum = sum(market.values())
    b = favorite_longshot_beliefs(_rows(), gamma=1.2)
    # 热门相对市场被抬高，冷门被压低
    assert b["France"] > market["France"] / msum
    assert b["Belgium"] < market["Belgium"] / msum


def test_top_n_limits():
    b = favorite_longshot_beliefs(_rows(), gamma=1.1, top_n=2)
    assert len(b) == 2
    assert set(b) == {"France", "Spain"}


def test_extract_beliefs_parses_json():
    text = '分析如下 {"beliefs": {"France": 0.18, "Argentina": 0.12}, "rationale": "x"} 完毕'
    b = _extract_beliefs(text)
    assert b == {"France": 0.18, "Argentina": 0.12}


def test_extract_beliefs_none_when_absent():
    assert _extract_beliefs("没有有效 JSON") is None
