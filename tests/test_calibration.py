"""校准单测：用构造的小数据集验证拟合方向，及队名/分组映射。不联网。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.tools.calibration import (  # noqa: E402
    calibrated_groups,
    dataset_name,
    fit_ratings,
)
from worldcup_betting.tools.historical_data import HistMatch  # noqa: E402


def _synth():
    """Strong 屡胜 Mid，Mid 屡胜 Weak —— 评分应 Strong>Mid>Weak。"""
    ms = []
    for _ in range(40):
        ms.append(HistMatch(date(2023, 1, 1), "Strong", "Mid", 3, 0, True, 1.0))
        ms.append(HistMatch(date(2023, 1, 1), "Mid", "Weak", 2, 0, True, 1.0))
        ms.append(HistMatch(date(2023, 1, 1), "Strong", "Weak", 4, 0, True, 1.0))
    return ms


def test_fit_orders_teams_by_strength():
    cal = fit_ratings(_synth(), iterations=300)
    r = cal.ratings
    assert r["strong"] > r["mid"] > r["weak"]


def test_fit_recovers_home_advantage():
    # 全部主场且主队净胜 → home_adv 应为正
    ms = [HistMatch(date(2023, 1, 1), "A", "B", 2, 1, False, 1.0) for _ in range(60)]
    ms += [HistMatch(date(2023, 1, 1), "B", "A", 2, 1, False, 1.0) for _ in range(60)]
    cal = fit_ratings(ms, iterations=200)
    assert cal.home_adv > 0.05


def test_ratings_centered_near_prior():
    cal = fit_ratings(_synth(), iterations=200)
    mean = sum(cal.ratings.values()) / len(cal.ratings)
    assert abs(mean - 50.0) < 1e-6


def test_dataset_name_alias_and_accents():
    assert dataset_name("USA") == "united states"
    assert dataset_name("Curacao") == "curacao"   # 重音被规范化去除
    assert dataset_name("Spain") == "spain"


def test_calibrated_groups_fallback_for_missing():
    # 拟合数据里没有任何 WC 队 → 全部回退到示意值
    cal = fit_ratings(_synth(), iterations=50)
    cg = calibrated_groups(cal)
    spain_power = next(p for teams in cg.values() for n, p in teams if n == "Spain")
    assert spain_power == 92  # 原示意值未被覆盖
