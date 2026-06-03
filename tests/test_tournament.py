"""赛制蒙特卡洛模拟器单测。"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.tools.tournament import (  # noqa: E402
    championship_probabilities,
    expected_goals,
    sim_knockout,
    simulate_tournament,
)
from worldcup_betting.tools.wc2026_data import GROUPS, default_ratings  # noqa: E402


def test_expected_goals_monotonic():
    # 实力越强期望进球越多；势均力敌时相等
    sa, sb = expected_goals(90, 60)
    assert sa > sb
    eq_a, eq_b = expected_goals(70, 70)
    assert abs(eq_a - eq_b) < 1e-9


def test_data_is_48_teams_12_groups():
    assert len(GROUPS) == 12
    assert all(len(v) == 4 for v in GROUPS.values())
    assert len(default_ratings()) == 48  # 队名唯一


def test_simulate_returns_valid_champion():
    rng = random.Random(0)
    champ = simulate_tournament(GROUPS, rng)
    assert champ in default_ratings()


def test_knockout_stronger_team_wins_more():
    rng = random.Random(1)
    ratings = {"Strong": 95.0, "Weak": 40.0}
    wins = sum(sim_knockout("Strong", "Weak", ratings, rng) == "Strong" for _ in range(2000))
    assert wins > 1500  # 强队应大概率晋级


def test_probabilities_sum_to_one_and_favor_strong():
    res = championship_probabilities(n_sims=2000, seed=7)
    assert abs(sum(res.probabilities.values()) - 1.0) < 1e-9
    # 强队(France power93)夺冠概率应高于弱队
    assert res.probabilities.get("France", 0) > res.probabilities.get("New Zealand", 0)


def test_reproducible_with_seed():
    a = championship_probabilities(n_sims=1000, seed=99).probabilities
    b = championship_probabilities(n_sims=1000, seed=99).probabilities
    assert a == b
