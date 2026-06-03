"""赛制蒙特卡洛夺冠模拟 → 对比真实盘口 → 价值扫描。

模拟整届世界杯上万遍得出各队夺冠概率(独立于盘口的观点)，与 Polymarket 真实夺冠盘
对比找分歧，再喂给现有价值扫描内核(接口不变、下游零改动)。

用法：
    python examples/tournament_sim.py                 # 1万届
    python examples/tournament_sim.py --sims 30000

⚠ 实力评分为示意值，未校准；当前模拟相对盘口偏分散，仅演示机制，勿据此下注。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.tools.outright import scan_outright_value  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketClient,
    PolymarketError,
    event_to_outright_probs,
)
from worldcup_betting.tools.tournament import championship_probabilities  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sims", type=int, default=10_000)
    p.add_argument("--bankroll", type=float, default=10_000.0)
    args = p.parse_args()

    print(f"模拟 {args.sims:,} 届世界杯…")
    sim = championship_probabilities(n_sims=args.sims)
    beliefs = {t: pr for t, pr in sim.probabilities.items() if pr >= 0.005}

    # 真实盘口
    market_prob: dict[str, float] = {}
    try:
        event = PolymarketClient().get_event_by_slug("world-cup-winner")
        for r in event_to_outright_probs(event):
            market_prob[str(r["team"]).lower()] = r["fair_prob"]
    except PolymarketError as e:
        print(f"[warn] 盘口拉取失败，仅显示模拟结果：{e}")

    print(f"\n{'球队':<14}{'模拟夺冠':>9}{'盘口隐含':>9}{'差异':>9}")
    for team, sp in list(beliefs.items())[:14]:
        mp = market_prob.get(team.lower())
        if mp is None:
            print(f"{team:<14}{sp:>9.1%}{'—':>9}{'—':>9}")
        else:
            print(f"{team:<14}{sp:>9.1%}{mp:>9.1%}{sp - mp:>+9.1%}")

    # 接入现有价值扫描（接口不变）
    if market_prob:
        cfg = RiskConfig(bankroll=args.bankroll)
        rows = event_to_outright_probs(PolymarketClient().get_event_by_slug("world-cup-winner"))
        opps = scan_outright_value(rows, beliefs, cfg)
        values = [o for o in opps if o.is_value]
        print(f"\n扫描出 {len(values)} 个'价值机会' —— 但这是反面教材：")
        for o in values[:6]:
            print(f"  ⚠ {o.team:<12} edge {o.edge:+.1%}  (模拟 {o.user_prob:.1%} vs 盘口 {o.market_prob:.1%})")
        print("  这些夸张 edge 全是未校准模型把弱队概率估太高的产物，绝不可下注。")
        print("  正确流程：先校准实力分，让模拟与盘口在大热门上量级一致，再看残余分歧。")

    print("\n⚠ 评分未校准，仅演示机制(第1步)。第2步需用 Elo/历史比分拟合实力分后方可使用。")


if __name__ == "__main__":
    main()
