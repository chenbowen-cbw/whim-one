"""真实 Polymarket 行情演示（联网，无需 API Key）。

用法：
    python examples/polymarket_live.py                 # 夺冠盘真实概率排行
    python examples/polymarket_live.py --list          # 列出对阵/世界杯类赛事
    python examples/polymarket_live.py --slug <slug> --home "队A" --away "队B"
                                                       # 解析某场 1X2 赛事(开盘后可用)

数据源：https://gamma-api.polymarket.com （公开端点）。
逐场胜平负市场通常临近开赛才开盘；未开盘时用夺冠盘演示真实数据流。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.models import Outcome  # noqa: E402
from worldcup_betting.tools.analytics import overround, remove_vig  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketClient,
    PolymarketError,
    event_to_market_odds,
    event_to_outright_probs,
)

_CN = {Outcome.HOME: "主胜", Outcome.DRAW: "平局", Outcome.AWAY: "客胜"}


def show_outright(client: PolymarketClient) -> None:
    event = client.get_event_by_slug("world-cup-winner")
    rows = event_to_outright_probs(event)
    print(f"\n【世界杯夺冠盘 · 真实 Polymarket 行情】 {len(rows)} 队")
    print(f"slug={event.get('slug')}  负责解析: Yes价→去抽水概率\n")
    print(f"  {'球队':<16}{'夺冠概率':>8}{'赔率':>8}{'流动性($)':>14}")
    for r in rows[:15]:
        print(f"  {str(r['team']):<16}{r['fair_prob']:>8.1%}{r['decimal_odds']:>8.2f}{r['liquidity']:>14,.0f}")
    print(f"\n  共 {len(rows)} 队；原始 Yes 价合计 = {sum(r['raw_price'] for r in rows):.3f}（>1 即场内抽水）")


def list_events(client: PolymarketClient) -> None:
    evs = client.find_soccer_events(limit=300)
    print(f"\n找到对阵/世界杯类赛事 {len(evs)} 个：")
    for e in evs:
        print(f"  - {e.get('title')}  | 子市场 {len(e.get('markets', []))}  | slug: {e.get('slug')}")


def show_match(client: PolymarketClient, slug: str, home: str, away: str) -> None:
    event = client.get_event_by_slug(slug)
    odds = event_to_market_odds(
        event, match_id=slug, mapping={Outcome.HOME: home, Outcome.AWAY: away}
    )
    fair = remove_vig(odds.decimal_odds)
    print(f"\n【{home} vs {away} · 真实 Polymarket 1X2】 slug={slug}")
    for o in Outcome:
        print(f"  {_CN[o]}: 赔率 {odds.decimal_odds[o]:.2f}  去抽水隐含 {fair[o]:.1%}")
    print(f"  抽水 overround = {overround(odds.decimal_odds) - 1:+.1%}")
    print(f"  风控信号: {odds.metadata}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true")
    p.add_argument("--slug")
    p.add_argument("--home")
    p.add_argument("--away")
    args = p.parse_args()

    client = PolymarketClient()
    try:
        if args.list:
            list_events(client)
        elif args.slug:
            if not (args.home and args.away):
                p.error("--slug 需配合 --home 与 --away")
            show_match(client, args.slug, args.home, args.away)
        else:
            show_outright(client)
    except PolymarketError as e:
        print(f"数据拉取失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
