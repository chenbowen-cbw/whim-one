"""赛制蒙特卡洛夺冠模拟器。

把整届世界杯按真实赛制打很多遍，统计各队夺冠频率作为"真实"夺冠概率——
这是独立于盘口的观点来源，替代简陋的热门-冷门幂变换。

模型链：
  实力分(power) ─► 单场期望进球(泊松/指数式) ─► 抽样比分 ─► 胜平负/晋级
  小组赛(12组×6场) ─► 名次 ─► 出线(各组前2 + 最佳8个第3) ─► 淘汰赛(单场+点球) ─► 冠军

赛制说明(2026)：48队/12组，每组前2(24) + 成绩最好的8个第3名 = 32队进淘汰赛。
注：淘汰赛对阵采用"按小组赛表现强弱播种"的标准签表，是对官方固定签表的简化(已注释)。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

BASE_GOALS = 1.30        # 中性实力对决的单队期望进球
POWER_SENSITIVITY = 0.9  # 实力差对进球的放大系数（作用于 (powerA-powerB)/100）


def _poisson(lam: float, rng: random.Random) -> int:
    """Knuth 算法抽样泊松分布（lam 较小时高效）。"""
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def expected_goals(power_a: float, power_b: float) -> tuple[float, float]:
    """由双方实力分给出各自期望进球。"""
    d = (power_a - power_b) / 100.0
    la = BASE_GOALS * math.exp(POWER_SENSITIVITY * d)
    lb = BASE_GOALS * math.exp(POWER_SENSITIVITY * -d)
    return la, lb


def sim_score(power_a: float, power_b: float, rng: random.Random) -> tuple[int, int]:
    la, lb = expected_goals(power_a, power_b)
    return _poisson(la, rng), _poisson(lb, rng)


def sim_knockout(name_a: str, name_b: str, ratings: dict[str, float], rng: random.Random) -> str:
    """淘汰赛：平局则按实力加权"点球"定胜负，返回晋级者队名。"""
    ga, gb = sim_score(ratings[name_a], ratings[name_b], rng)
    if ga > gb:
        return name_a
    if gb > ga:
        return name_b
    # 点球：强队略占优
    pa = ratings[name_a]
    pb = ratings[name_b]
    return name_a if rng.random() < pa / (pa + pb) else name_b


@dataclass
class _Standing:
    name: str
    pts: int = 0
    gf: int = 0
    ga: int = 0
    tiebreak: float = 0.0  # 随机次级排序，避免确定性并列

    @property
    def gd(self) -> int:
        return self.gf - self.ga

    @property
    def sort_key(self):
        return (-self.pts, -self.gd, -self.gf, self.tiebreak)


def _sim_group(teams: list[tuple[str, float]], rng: random.Random) -> list[_Standing]:
    table = {name: _Standing(name, tiebreak=rng.random()) for name, _ in teams}
    powers = dict(teams)
    names = [n for n, _ in teams]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            ga, gb = sim_score(powers[a], powers[b], rng)
            table[a].gf += ga; table[a].ga += gb
            table[b].gf += gb; table[b].ga += ga
            if ga > gb:
                table[a].pts += 3
            elif gb > ga:
                table[b].pts += 3
            else:
                table[a].pts += 1; table[b].pts += 1
    return sorted(table.values(), key=lambda s: s.sort_key)


def _knockout_bracket(qualifiers: list[str], ratings: dict[str, float], rng: random.Random) -> str:
    """对 32 强按实力播种成标准签表(1v32...)，逐轮单场淘汰，返回冠军。"""
    return _knockout_staged(qualifiers, ratings, rng, {n: 0 for n in qualifiers})


# 淘汰赛阶段编码：1=进淘汰赛(R32) 2=进16强 3=进8强 4=进4强 5=进决赛 6=夺冠
STAGE = {"reach_r16": 2, "reach_qf": 3, "reach_sf": 4, "reach_final": 5, "champion": 6}


def _knockout_staged(qualifiers: list[str], ratings: dict[str, float],
                     rng: random.Random, stages: dict[str, int]) -> str:
    """逐轮单场淘汰，记录每队达到的最远阶段到 stages，返回冠军。"""
    seeded = sorted(qualifiers, key=lambda n: -ratings[n])
    n = len(seeded)
    bracket = [(seeded[i], seeded[n - 1 - i]) for i in range(n // 2)]
    stage = 2  # 首轮(R32)胜者 → 进16强(=2)
    while True:
        winners = [sim_knockout(a, b, ratings, rng) for a, b in bracket]
        for w in winners:
            if stage > stages.get(w, 0):
                stages[w] = stage
        if len(winners) == 1:
            return winners[0]
        bracket = [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)]
        stage += 1


def simulate_tournament_detailed(
    groups: dict[str, list[tuple[str, float]]], rng: random.Random
) -> tuple[dict[str, int], list[str], str]:
    """模拟一届，返回 (各队最远阶段, 各组头名列表, 冠军)。

    阶段：0=止步小组 1=进淘汰赛 2=16强 3=8强 4=4强 5=决赛 6=夺冠。
    """
    ratings = {name: p for teams in groups.values() for name, p in teams}
    stages = {name: 0 for name in ratings}
    group_winners: list[str] = []
    winners_runners: list[str] = []
    thirds: list[_Standing] = []
    for teams in groups.values():
        table = _sim_group(teams, rng)
        group_winners.append(table[0].name)
        winners_runners.append(table[0].name)
        winners_runners.append(table[1].name)
        thirds.append(table[2])

    best_thirds = sorted(thirds, key=lambda s: (-s.pts, -s.gd, -s.gf, s.tiebreak))[:8]
    qualifiers = winners_runners + [s.name for s in best_thirds]  # 32 队
    for q in qualifiers:
        stages[q] = max(stages[q], 1)

    champion = _knockout_staged(qualifiers, ratings, rng, stages)
    return stages, group_winners, champion


def simulate_tournament(groups: dict[str, list[tuple[str, float]]], rng: random.Random) -> str:
    """模拟一届，返回冠军队名。"""
    return simulate_tournament_detailed(groups, rng)[2]


def team_groups(groups: dict[str, list[tuple[str, float]]] | None = None) -> dict[str, str]:
    """{队名: 所在组(A..L)}。"""
    from .wc2026_data import GROUPS

    groups = groups or GROUPS
    return {name: g for g, teams in groups.items() for name, _ in teams}


def tournament_probabilities(
    groups: dict[str, list[tuple[str, float]]] | None = None,
    *,
    n_sims: int = 10_000,
    seed: int = 42,
) -> dict[str, dict[str, float]]:
    """一次模拟同时统计多种结果的概率。

    返回 {结果类型: {队名: 概率}}，结果类型含：
      group_winner(小组头名) / reach_r16 / reach_qf / reach_sf / reach_final / champion
    其中 reach_* 为"至少进到该轮"的累计概率（各队独立，不必和为1）；
    champion / group_winner 在各自范围内互斥（和≈1）。
    """
    from .wc2026_data import GROUPS

    groups = groups or GROUPS
    rng = random.Random(seed)
    teams = [name for ts in groups.values() for name, _ in ts]
    keys = ["group_winner", "reach_r16", "reach_qf", "reach_sf", "reach_final", "champion"]
    cnt = {k: {t: 0 for t in teams} for k in keys}

    for _ in range(n_sims):
        stages, gws, _champ = simulate_tournament_detailed(groups, rng)
        for t, st in stages.items():
            if st >= 2: cnt["reach_r16"][t] += 1
            if st >= 3: cnt["reach_qf"][t] += 1
            if st >= 4: cnt["reach_sf"][t] += 1
            if st >= 5: cnt["reach_final"][t] += 1
            if st >= 6: cnt["champion"][t] += 1
        for t in gws:
            cnt["group_winner"][t] += 1

    return {k: {t: c / n_sims for t, c in d.items()} for k, d in cnt.items()}


@dataclass
class SimResult:
    n_sims: int
    probabilities: dict[str, float]      # {队名: 夺冠概率}，降序
    titles: dict[str, int] = field(default_factory=dict)


def championship_probabilities(
    groups: dict[str, list[tuple[str, float]]] | None = None,
    *,
    n_sims: int = 10_000,
    seed: int = 42,
) -> SimResult:
    """跑 n_sims 届，返回各队夺冠概率。"""
    probs = tournament_probabilities(groups, n_sims=n_sims, seed=seed)["champion"]
    probs = dict(sorted(probs.items(), key=lambda kv: -kv[1]))
    titles = {t: round(p * n_sims) for t, p in probs.items()}
    return SimResult(n_sims=n_sims, probabilities=probs, titles=titles)


def simulation_beliefs(
    *,
    n_sims: int = 10_000,
    seed: int = 42,
    min_prob: float = 0.005,
) -> dict[str, float]:
    """供价值扫描使用的 {队名: 夺冠概率}，过滤掉概率过低的长尾。"""
    res = championship_probabilities(n_sims=n_sims, seed=seed)
    return {team: p for team, p in res.probabilities.items() if p >= min_prob}
