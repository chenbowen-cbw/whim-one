"""历史国际比赛比分加载（用于校准实力评分）。

数据源：martj42/international_results（CC0，1872 至今所有国际A级赛比分）。
首次下载后缓存到本地，避免重复联网。

每场比赛带一个权重 = 赛事重要性 × 时间衰减，让"近期 + 大赛"的比分影响更大。
"""

from __future__ import annotations

import csv
import math
import os
import urllib.request
from dataclasses import dataclass
from datetime import date

DATA_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
CACHE = os.path.join(os.path.dirname(__file__), "_results_cache.csv")

# 赛事重要性权重（子串匹配 tournament 字段）
_IMPORTANCE = [
    ("FIFA World Cup", 3.0),
    ("World Cup qualification", 1.6),
    ("UEFA Euro", 2.2),
    ("Copa América", 2.2),
    ("African Cup", 1.8),
    ("AFC Asian Cup", 1.8),
    ("UEFA Nations", 1.6),
    ("Confederations", 1.6),
    ("Friendly", 0.7),
]


@dataclass
class HistMatch:
    d: date
    home: str
    away: str
    hs: int
    as_: int
    neutral: bool
    weight: float


def _importance(tournament: str) -> float:
    for key, w in _IMPORTANCE:
        if key.lower() in tournament.lower():
            return w
    return 1.0  # 其它正式赛默认 1.0


def ensure_cached(url: str = DATA_URL, path: str = CACHE) -> str:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        req = urllib.request.Request(url, headers={"User-Agent": "worldcup-betting/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as f:
            f.write(resp.read())
    return path


def load_matches(
    *,
    since_year: int = 2011,
    half_life_years: float = 7.0,
    as_of: date | None = None,
    path: str | None = None,
) -> list[HistMatch]:
    """加载并加权历史比赛。

    时间衰减：weight ×= 0.5 ** (age_years / half_life_years)。
    """
    path = path or ensure_cached()
    as_of = as_of or date.today()
    out: list[HistMatch] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                d = date.fromisoformat(row["date"])
                hs, as_ = int(row["home_score"]), int(row["away_score"])
            except (ValueError, KeyError):
                continue
            if d.year < since_year or d > as_of:
                continue
            age = (as_of - d).days / 365.25
            decay = 0.5 ** (age / half_life_years)
            w = _importance(row["tournament"]) * decay
            out.append(
                HistMatch(d, row["home_team"], row["away_team"], hs, as_,
                          row["neutral"].strip().upper() == "TRUE", w)
            )
    return out
