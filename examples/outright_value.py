"""真实数据价值扫描：拿你对某队夺冠的判断，对比 Polymarket 真实盘口算 edge。

用法（你的概率判断，可多队；不传则用示例）：
    python examples/outright_value.py --bet Argentina=0.15 --bet Brazil=0.12
    python examples/outright_value.py --bankroll 10000 --bet "USA=0.03"

数据源：Polymarket Gamma API 真实夺冠盘。系统只负责去抽水、算 edge/凯利、
用真实流动性与风控闸过滤、给金额；概率判断由你给出。
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


def parse_bets(items: list[str]) -> dict[str, float]:
    beliefs: dict[str, float] = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--bet 格式应为 队名=概率，得到 {it!r}")
        name, val = it.rsplit("=", 1)
        beliefs[name.strip()] = float(val)
    return beliefs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bet", action="append", default=[], help="队名=你的夺冠概率，可多次")
    p.add_argument("--bankroll", type=float, default=10_000.0)
    p.add_argument("--min-liquidity", type=float, default=50_000.0)
    args = p.parse_args()

    beliefs = parse_bets(args.bet) or {"Argentina": 0.15, "Brazil": 0.12, "USA": 0.03}
    cfg = RiskConfig(bankroll=args.bankroll, min_liquidity=args.min_liquidity)

    client = PolymarketClient()
    try:
        event = client.get_event_by_slug("world-cup-winner")
    except PolymarketError as e:
        print(f"数据拉取失败：{e}", file=sys.stderr)
        sys.exit(1)

    rows = event_to_outright_probs(event)
    opps = scan_outright_value(rows, beliefs, cfg)

    print("=" * 70)
    print(f"世界杯夺冠盘 · 价值扫描（真实 Polymarket 行情）  bankroll=${cfg.bankroll:,.0f}")
    print(f"风控：edge≥{cfg.edge_threshold:.0%}  {cfg.kelly_scale:.0%}凯利  "
          f"单注≤{cfg.max_fraction_per_bet:.0%}  组合≤{cfg.max_total_exposure:.0%}  "
          f"流动性≥${cfg.min_liquidity:,.0f}")
    print("=" * 70)

    for o in opps:
        tag = "✅ 价值" if o.is_value else "—  跳过"
        print(f"\n[{tag}] {o.team}")
        print(f"   你的判断 {o.user_prob:.1%}  vs  盘口隐含 {o.market_prob:.1%}  "
              f"(赔率 {o.decimal_odds:.2f}, 流动性 ${o.liquidity:,.0f})")
        print(f"   edge {o.edge:+.1%}   {o.reason}")
        if o.is_value:
            print(f"   ▶ 建议下注 {o.stake_fraction:.1%} 资金 ≈ ${o.stake_amount:,.0f}")

    total = sum(o.stake_amount for o in opps if o.is_value)
    print(f"\n合计建议投入：${total:,.0f}（占 bankroll {total / cfg.bankroll:.1%}）")
    print("\n⚠ 仅供研究参考，不构成投注建议。概率判断与最终决策由你负责，请遵守当地法规、理性投注。")


if __name__ == "__main__":
    main()
