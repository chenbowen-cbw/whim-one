"""逐场胜平负(1X2)真实分析。

自动发现 Polymarket 上已开盘的世界杯逐场赛事，对每场：
  真实 1X2 赔率 → 去抽水 → 盘口基线预测 → 价值扫描 → 投注推荐。

逐场市场通常临近开赛(6/11起)才开盘；未发现时给出明确提示并演示离线 fixture。

用法：
    python examples/match_live.py                     # 自动发现并分析
    python examples/match_live.py --slug <slug>       # 指定某场赛事 slug
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.models import MarketOdds, Outcome  # noqa: E402
from worldcup_betting.risk import build_recommendations  # noqa: E402
from worldcup_betting.tools.analytics import find_value_bets, overround, remove_vig  # noqa: E402
from worldcup_betting.tools.baseline_model import market_devig_prediction  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketClient,
    PolymarketError,
    discover_match_odds,
    parse_match_title,
)

_CN = {Outcome.HOME: "主胜", Outcome.DRAW: "平局", Outcome.AWAY: "客胜"}


def analyze_one(odds: MarketOdds, title: str, cfg: RiskConfig) -> None:
    fair = remove_vig(odds.decimal_odds)
    pred = market_devig_prediction(odds)
    assessments = find_value_bets(pred, [odds], edge_threshold=cfg.edge_threshold,
                                  kelly_scale=cfg.kelly_scale, max_fraction=cfg.max_fraction_per_bet)
    recs = build_recommendations(pred, assessments, cfg)

    print(f"\n{'=' * 64}\n{title}    (slug={odds.metadata.get('slug')})\n{'=' * 64}")
    print("真实 1X2 盘口 / 去抽水隐含 / 基线预测：")
    for o in Outcome:
        print(f"  {_CN[o]}: 赔率 {odds.decimal_odds[o]:.2f}  隐含 {fair[o]:.1%}  "
              f"基线 {pred.probabilities[o]:.1%}")
    print(f"  抽水 {overround(odds.decimal_odds) - 1:+.1%}  流动性 ${odds.metadata.get('liquidity', 0):,.0f}")
    if recs:
        for r in recs:
            print(f"  ▶ 押 {_CN[r.outcome]} @ {r.decimal_odds:.2f} | EV {r.expected_value:+.1%} "
                  f"| 建议 {r.stake_fraction:.1%} ≈${r.stake_amount:,.0f}")
    else:
        print("  无满足风控的价值机会（基线仅凭盘口，通常无 edge，符合预期）。")


def _fixture_event() -> dict:
    """离线演示用：模拟一场已开盘的 negRisk 三选赛事。"""
    return {
        "title": "Argentina vs. Mexico",
        "slug": "demo-arg-vs-mex",
        "markets": [
            {"groupItemTitle": "Argentina", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0.60","0.40"]', "liquidityNum": "120000", "spread": "0.01"},
            {"groupItemTitle": "Draw", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0.25","0.75"]', "liquidityNum": "80000", "spread": "0.01"},
            {"groupItemTitle": "Mexico", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0.18","0.82"]', "liquidityNum": "90000", "spread": "0.02"},
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug")
    p.add_argument("--bankroll", type=float, default=10_000.0)
    args = p.parse_args()
    cfg = RiskConfig(bankroll=args.bankroll)
    client = PolymarketClient()

    try:
        if args.slug:
            events = [client.get_event_by_slug(args.slug)]
        else:
            events = client.find_match_events()
    except PolymarketError as e:
        print(f"数据拉取失败：{e}", file=sys.stderr)
        sys.exit(1)

    analyzable = [(e, discover_match_odds(e)) for e in events]
    analyzable = [(e, o) for e, o in analyzable if o is not None]

    if not analyzable:
        print("ℹ 目前 Polymarket 尚无可解析的世界杯逐场胜平负市场（一般临近开赛才开盘）。")
        print("  用离线 fixture 演示完整逐场流程：")
        ev = _fixture_event()
        analyze_one(discover_match_odds(ev), ev["title"], cfg)
        return

    print(f"发现 {len(analyzable)} 场可分析的逐场赛事。")
    for e, o in analyzable:
        title = e.get("title") or "/".join(parse_match_title(e.get("title", "")) or [])
        analyze_one(o, title, cfg)

    print("\n⚠ 仅供研究参考。基线预测仅凭盘口，价值需结合你的独立判断；最终决策与合规由你负责。")


if __name__ == "__main__":
    main()
