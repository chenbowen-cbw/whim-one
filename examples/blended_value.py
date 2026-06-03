"""完整闭环：校准 → 模拟 → 向盘口收缩 → 价值扫描。

把校准模拟得到的夺冠概率，按置信度 λ 向真实盘口收缩，再算 edge。
λ 越小越保守(贴近盘口、edge 越小)。这能驯服未校准/欠拟合模型的夸张假信号，
只在模型相对盘口有明确观点处，给出克制的价值建议。

用法：
    python examples/blended_value.py                 # λ=0.35
    python examples/blended_value.py --weight 0.5 --sims 20000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.tools.blending import blend_beliefs  # noqa: E402
from worldcup_betting.tools.calibration import (  # noqa: E402
    calibrated_groups,
    dataset_name,
    fit_ratings,
)
from worldcup_betting.tools.historical_data import load_matches  # noqa: E402
from worldcup_betting.tools.outright import scan_outright_value  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketClient,
    PolymarketError,
    event_to_outright_probs,
)
from worldcup_betting.tools.tournament import championship_probabilities  # noqa: E402
from worldcup_betting.tools.wc2026_data import GROUPS  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--weight", type=float, default=0.35, help="对模型的信任度λ(0=纯盘口,1=纯模型)")
    p.add_argument("--sims", type=int, default=10_000)
    p.add_argument("--bankroll", type=float, default=10_000.0)
    args = p.parse_args()

    print("① 校准评分 → ② 模拟 → ③ 向盘口收缩 → ④ 价值扫描")
    cal = fit_ratings(load_matches())
    sim = championship_probabilities(calibrated_groups(cal, GROUPS), n_sims=args.sims)
    model = {dataset_name(t): pr for t, pr in sim.probabilities.items()}

    try:
        ev = PolymarketClient().get_event_by_slug("world-cup-winner")
        rows = event_to_outright_probs(ev)
    except PolymarketError as e:
        print(f"盘口拉取失败：{e}", file=sys.stderr)
        sys.exit(1)
    market = {dataset_name(str(r["team"])): r["fair_prob"] for r in rows}

    blended = blend_beliefs(model, market, weight=args.weight)

    # 价值扫描需用盘口里的原始队名，做 规范名→原始名 的回映射
    norm_to_team = {dataset_name(str(r["team"])): str(r["team"]) for r in rows}
    beliefs = {norm_to_team[k]: v for k, v in blended.items() if k in norm_to_team}

    # 极端冷门(盘口<2%)不碰：模型在弱队上不可信，且长赔率含冷门溢价
    cfg = RiskConfig(bankroll=args.bankroll, min_market_prob=0.02)
    opps = scan_outright_value(rows, beliefs, cfg)

    print(f"\nλ={args.weight}  (λ→0 越贴近盘口、越保守)")
    print(f"{'球队':<14}{'模型':>7}{'盘口':>7}{'收缩后':>8}{'edge':>8}{'建议':>8}")
    shown = 0
    for o in opps:
        nk = dataset_name(o.team)
        m = model.get(nk)
        ms = f"{m:.1%}" if m is not None else "—"
        stake = f"{o.stake_fraction:.1%}" if o.is_value else "—"
        flag = "✅" if o.is_value else "  "
        print(f"{flag}{o.team:<12}{ms:>7}{o.market_prob:>7.1%}{o.user_prob:>8.1%}"
              f"{o.edge:>+8.1%}{stake:>8}")
        shown += 1
        if shown >= 16:
            break

    values = [o for o in opps if o.is_value]
    total = sum(o.stake_amount for o in values)
    print(f"\n价值机会 {len(values)} 个，合计建议 ${total:,.0f}（占 {total/cfg.bankroll:.1%}）")
    print("注意：收缩后 edge 已被压到合理量级；λ 越小越保守。")
    print("⚠ 模型仍有已知偏差，本输出仅供研究，勿据此下注。")


if __name__ == "__main__":
    main()
