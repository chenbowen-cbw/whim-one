"""闭环：分析智能体自动产出夺冠概率 → 价值扫描 → 投注推荐（全程真实行情）。

用法：
    python examples/outright_auto.py                 # 确定性分析器(降级)，无需 Key
    ANTHROPIC_API_KEY=sk-... python examples/outright_auto.py --agents   # LLM 分析师

与 outright_value.py 的区别：概率判断不再手填，而是由分析器/LLM 自动产出，形成闭环。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.agents.outright_analyst import produce_outright_beliefs  # noqa: E402
from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.tools.outright import scan_outright_value  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketClient,
    PolymarketError,
    event_to_outright_probs,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agents", action="store_true", help="启用 LLM 分析师(需 API Key)")
    p.add_argument("--bankroll", type=float, default=10_000.0)
    p.add_argument("--gamma", type=float, default=1.12, help="基线热门-冷门修正强度")
    p.add_argument("--top", type=int, default=10, help="基线只覆盖前 N 支热门")
    args = p.parse_args()

    client = PolymarketClient()
    try:
        event = client.get_event_by_slug("world-cup-winner")
    except PolymarketError as e:
        print(f"数据拉取失败：{e}", file=sys.stderr)
        sys.exit(1)
    rows = event_to_outright_probs(event)

    beliefs, source = produce_outright_beliefs(
        rows, use_llm=args.agents, gamma=args.gamma, top_n=args.top
    )

    cfg = RiskConfig(bankroll=args.bankroll)
    opps = scan_outright_value(rows, beliefs, cfg)

    print("=" * 72)
    print(f"夺冠盘闭环分析（真实 Polymarket 行情）  bankroll=${cfg.bankroll:,.0f}")
    print(f"概率来源：{source}")
    print("=" * 72)
    print(f"\n{'球队':<14}{'分析概率':>9}{'盘口隐含':>9}{'edge':>9}{'建议仓位':>10}")
    for o in opps:
        mark = "✅" if o.is_value else "  "
        stake = f"{o.stake_fraction:.1%}" if o.is_value else "—"
        print(f"{mark}{o.team:<12}{o.user_prob:>9.1%}{o.market_prob:>9.1%}"
              f"{o.edge:>+9.1%}{stake:>10}")

    total = sum(o.stake_amount for o in opps if o.is_value)
    n = sum(1 for o in opps if o.is_value)
    print(f"\n价值机会 {n} 个，合计建议投入 ${total:,.0f}（占 {total / cfg.bankroll:.1%}）")
    print("\n⚠ 仅供研究参考。分析器/LLM 的概率是模型估计，非事实；最终决策与合规由你负责。")


if __name__ == "__main__":
    main()
