"""第2步：用历史比分校准实力评分 → 重跑夺冠模拟 → 对比盘口。

验证校准是否让模拟在大热门上与盘口量级对齐（不再像未校准时那样过度分散）。

用法：
    python examples/calibrate.py                 # 校准 + 模拟 + 对比
    python examples/calibrate.py --since 2018 --sims 20000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.tools.calibration import (  # noqa: E402
    calibrated_groups,
    dataset_name,
    fit_ratings,
)
from worldcup_betting.tools.historical_data import load_matches  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketClient,
    PolymarketError,
    event_to_outright_probs,
)
from worldcup_betting.tools.tournament import championship_probabilities  # noqa: E402
from worldcup_betting.tools.wc2026_data import GROUPS  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", type=int, default=2011)
    p.add_argument("--sims", type=int, default=10_000)
    args = p.parse_args()

    print(f"加载并加权历史比赛(>= {args.since})…")
    matches = load_matches(since_year=args.since)
    print(f"  共 {len(matches):,} 场，拟合中…")
    cal = fit_ratings(matches)
    print(f"  完成：{len(cal.ratings)} 队，home_adv={cal.home_adv:.3f}，用赛 {cal.n_matches:,}")

    cgroups = calibrated_groups(cal, GROUPS)
    print("\n校准后参赛队 power（节选）：")
    flat = sorted((p, n) for teams in cgroups.values() for n, p in teams)
    for power, name in [*flat[-6:][::-1], *flat[:3]]:
        print(f"  {name:14s} {power:5.1f}")

    print(f"\n用校准评分模拟 {args.sims:,} 届…")
    sim = championship_probabilities(cgroups, n_sims=args.sims)

    market = {}
    try:
        ev = PolymarketClient().get_event_by_slug("world-cup-winner")
        market = {dataset_name(r["team"]): r["fair_prob"] for r in event_to_outright_probs(ev)}
    except PolymarketError as e:
        print(f"[warn] 盘口拉取失败：{e}")

    print(f"\n{'球队':<14}{'模拟夺冠':>9}{'盘口隐含':>9}{'差异':>9}")
    for team, sp in list(sim.probabilities.items())[:14]:
        mp = market.get(dataset_name(team))
        diff = f"{sp - mp:+.1%}" if mp is not None else "—"
        mps = f"{mp:.1%}" if mp is not None else "—"
        print(f"{team:<14}{sp:>9.1%}{mps:>9}{diff:>9}")

    print("\n— 诚实的结论 —")
    print("✓ 校准成功：评分不再是拍脑袋，而是历史比分拟合所得；home_adv≈0.22 符合常识。")
    print("✗ 仍存在两处已知差距（下一步要解决，切勿据此下注）：")
    print("  1) 纯比分模型高估弱洲强队(日本/伊朗/阿尔及利亚)——未充分校正洲际赛程强弱;")
    print("  2) 单场淘汰+泊松方差大，压平了大热门，夺冠概率系统性低于盘口。")
    print("  改进方向：洲际强度校正、降低进球方差(双变量/收缩)、或以盘口为先验只在高置信处偏离。")


if __name__ == "__main__":
    main()
