"""Polymarket 真实数据源（Gamma API）。

数据来源：https://gamma-api.polymarket.com  （公开、无需鉴权）

经实测确认的关键字段（/events 与 /markets 返回）：
- ``outcomes`` / ``outcomePrices``：**JSON 字符串**，需二次 json.loads，如 '["Yes","No"]' / '["0.6","0.4"]'
- ``groupItemTitle``：negRisk 分组事件中该子市场代表的选项（如球队名 / "Draw"）
- ``liquidityNum`` / ``spread`` / ``bestBid`` / ``bestAsk``：流动性与点差信号（供风控）
- ``slug`` / ``conditionId``：稳定标识，用于按 slug 精确拉取

足球胜平负在 Polymarket 有两种组织形式，本模块都支持：
1. 单一三选市场：一个 market，outcomes=["Argentina","Draw","Mexico"]，三个价格。
2. negRisk 分组事件：一个 event 含 3 个二元(Yes/No)子市场，各取 "Yes" 价为该结果隐含概率。

价格(0~1)即隐含概率，经 ``1/price`` 统一转十进制赔率，与体彩同坐标系比较。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from ..models import Bookmaker, MarketOdds, Outcome
from .analytics import polymarket_price_to_decimal
from .odds_providers import OddsProvider

GAMMA_BASE = "https://gamma-api.polymarket.com"


class PolymarketError(RuntimeError):
    """拉取或解析 Polymarket 数据失败。"""


def _get_json(url: str, timeout: float = 20.0, *, retries: int = 3, backoff: float = 0.6):
    """GET 并解析 JSON，对暂时性故障(5xx/超时/网络抖动)做退避重试。"""
    req = urllib.request.Request(url, headers={"User-Agent": "worldcup-betting/0.1"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:  # 4xx 不会自愈，直接失败
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    raise PolymarketError(f"请求失败 {url}: {last}") from last


def _parse_json_field(value, default):
    """Gamma 把数组字段编码成 JSON 字符串，这里安全解码。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


class PolymarketClient:
    """对 Gamma API 的薄封装。"""

    def __init__(self, base: str = GAMMA_BASE, timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def get_event_by_slug(self, slug: str) -> dict:
        data = _get_json(f"{self.base}/events/slug/{urllib.parse.quote(slug)}", self.timeout)
        return data[0] if isinstance(data, list) else data

    def list_events(self, *, limit: int = 100, active: bool = True, closed: bool = False) -> list[dict]:
        q = urllib.parse.urlencode({"limit": limit, "active": str(active).lower(),
                                    "closed": str(closed).lower()})
        data = _get_json(f"{self.base}/events?{q}", self.timeout)
        return data if isinstance(data, list) else data.get("data", [])

    def find_match_events(self, *, limit: int = 300) -> list[dict]:
        """筛出可解析的逐场胜平负赛事（标题含对阵 + 含 Draw 选项）。"""
        return [e for e in self.list_events(limit=limit) if is_three_way_match(e)]

    def find_soccer_events(self, *, limit: int = 200) -> list[dict]:
        """启发式筛出对阵类/世界杯赛事（标题含 ' vs '/'world cup'）。"""
        out = []
        for e in self.list_events(limit=limit):
            blob = (e.get("title", "") + " " + e.get("description", "")).lower()
            if " vs " in blob or " vs. " in blob or "world cup" in blob:
                out.append(e)
        return out


def _yes_price(market: dict) -> float | None:
    """从二元市场取 'Yes' 对应价格。"""
    outcomes = _parse_json_field(market.get("outcomes"), [])
    prices = _parse_json_field(market.get("outcomePrices"), [])
    for name, price in zip(outcomes, prices):
        if str(name).strip().lower() == "yes":
            try:
                return float(price)
            except (TypeError, ValueError):
                return None
    return None


def _match_outcome(label: str, mapping: dict[Outcome, str]) -> Outcome | None:
    """把选项标签（球队名/Draw）按子串映射到 HOME/DRAW/AWAY。"""
    low = label.strip().lower()
    if low in ("draw", "tie"):
        return Outcome.DRAW
    for outcome, needle in mapping.items():
        if needle and needle.strip().lower() in low:
            return outcome
    return None


def event_to_market_odds(
    event: dict,
    match_id: str,
    mapping: dict[Outcome, str],
) -> MarketOdds:
    """把一个 Polymarket 赛事(event)解析成胜平负 MarketOdds。

    mapping 形如 {Outcome.HOME: "Argentina", Outcome.AWAY: "Mexico"}；
    DRAW 由 "Draw"/"Tie" 自动识别。两种盘口形式都会尝试。
    """
    prices: dict[Outcome, float] = {}
    liquidity = 0.0
    spreads: dict[str, float] = {}

    markets = event.get("markets", []) or []

    # 形式 1：单一三选市场
    for m in markets:
        outcomes = _parse_json_field(m.get("outcomes"), [])
        oprices = _parse_json_field(m.get("outcomePrices"), [])
        if len(outcomes) >= 3 and len(oprices) >= 3:
            for name, price in zip(outcomes, oprices):
                oc = _match_outcome(str(name), mapping)
                if oc and oc not in prices:
                    try:
                        prices[oc] = float(price)
                    except (TypeError, ValueError):
                        pass
            if len(prices) == 3:
                liquidity += float(m.get("liquidityNum") or 0)
                break

    # 形式 2：negRisk 分组——每个子市场是一个二元(Yes/No)，groupItemTitle 是选项
    if len(prices) < 3:
        prices.clear()
        for m in markets:
            label = m.get("groupItemTitle") or m.get("question") or ""
            oc = _match_outcome(label, mapping)
            yp = _yes_price(m)
            if oc and yp is not None and oc not in prices:
                prices[oc] = yp
                liquidity += float(m.get("liquidityNum") or 0)
                if m.get("spread") is not None:
                    spreads[oc.value] = float(m["spread"])

    missing = [o for o in Outcome if o not in prices]
    if missing:
        raise PolymarketError(
            f"事件 {event.get('slug')} 未能解析出全部胜平负价格，缺少 {missing}。"
            f" 可用选项: {[m.get('groupItemTitle') or m.get('question') for m in markets]}"
        )

    # 极端价格(0/1)代表无有效盘口(已结算/无报价)，抛 PolymarketError 让上层走降级而非崩溃
    bad = {o.value: p for o, p in prices.items() if not 0.0 < p < 1.0}
    if bad:
        raise PolymarketError(
            f"事件 {event.get('slug')} 含越界价格(非0~1，无有效盘口): {bad}"
        )

    decimal = {o: polymarket_price_to_decimal(p) for o, p in prices.items()}
    return MarketOdds(
        bookmaker=Bookmaker.POLYMARKET,
        match_id=match_id,
        decimal_odds=decimal,
        metadata={
            "source": "polymarket-gamma",
            "slug": event.get("slug"),
            "liquidity": round(liquidity, 2),
            "spread": spreads,
            "raw_prices": {o.value: prices[o] for o in Outcome},
        },
    )


def event_to_outright_probs(event: dict) -> list[dict]:
    """把夺冠盘(negRisk 分组事件)解析为去抽水后的真实概率排行。

    每个子市场是二元(Yes/No)，Yes 价即该队夺冠隐含概率；全场按比例归一去抽水。
    返回按概率降序的 [{team, raw_price, fair_prob, decimal_odds, liquidity}]。
    """
    rows = []
    for m in event.get("markets", []) or []:
        yp = _yes_price(m)
        if yp is None or not 0.0 < yp < 1.0:  # 越界价格(0/1)=无有效盘口，跳过该队
            continue
        rows.append(
            {
                "team": m.get("groupItemTitle") or m.get("question"),
                "raw_price": yp,
                "decimal_odds": polymarket_price_to_decimal(yp),
                "liquidity": float(m.get("liquidityNum") or 0),
            }
        )
    total = sum(r["raw_price"] for r in rows)
    for r in rows:
        r["fair_prob"] = r["raw_price"] / total if total else 0.0
    rows.sort(key=lambda r: -r["fair_prob"])
    return rows


def parse_match_title(title: str) -> tuple[str, str] | None:
    """从赛事标题解析 (home, away)，识别 'A vs B' / 'A vs. B' / 'A v B'。

    Polymarket 习惯按 '主队 vs 客队' 排列；无法解析时返回 None。
    """
    import re as _re

    m = _re.search(r"(.+?)\s+vs\.?\s+(.+)", title, _re.IGNORECASE) or \
        _re.search(r"(.+?)\s+v\s+(.+)", title, _re.IGNORECASE)
    if not m:
        return None
    home, away = m.group(1).strip(), m.group(2).strip()
    # 去掉可能的赛事后缀，如 "(World Cup)"
    away = _re.split(r"[(\[|]", away)[0].strip()
    if home and away:
        return home, away
    return None


def is_three_way_match(event: dict) -> bool:
    """粗判一个 event 是否为可解析的胜平负赛事（标题含对阵且含 Draw 选项）。"""
    if not parse_match_title(event.get("title", "")):
        return False
    labels = [
        str(m.get("groupItemTitle") or m.get("question") or "").lower()
        for m in event.get("markets", []) or []
    ]
    has_draw = any(l in ("draw", "tie") for l in labels)
    # 单一三选市场的情况：outcomes 含 Draw
    for m in event.get("markets", []) or []:
        outs = [str(x).lower() for x in _parse_json_field(m.get("outcomes"), [])]
        if "draw" in outs or "tie" in outs:
            has_draw = True
    return has_draw


def discover_match_odds(event: dict) -> MarketOdds | None:
    """自动从一个对阵 event 解析出 1X2 MarketOdds（主/客按标题顺序）。

    成功返回 MarketOdds，失败(非对阵/未开三选)返回 None。
    """
    parsed = parse_match_title(event.get("title", ""))
    if not parsed:
        return None
    home, away = parsed
    mapping = {Outcome.HOME: home, Outcome.AWAY: away}
    try:
        return event_to_market_odds(event, match_id=event.get("slug", "unknown"), mapping=mapping)
    except PolymarketError:
        return None


class PolymarketProvider(OddsProvider):
    """真实 Polymarket 盘口 Provider。

    需要把内部 match_id 映射到 Polymarket 的 event slug 与队名，
    通过 registry 注入：{match_id: (slug, {Outcome.HOME: "队A", Outcome.AWAY: "队B"})}。
    """

    def __init__(self, registry: dict[str, tuple[str, dict[Outcome, str]]],
                 client: PolymarketClient | None = None):
        self.registry = registry
        self.client = client or PolymarketClient()

    @property
    def bookmaker(self) -> Bookmaker:
        return Bookmaker.POLYMARKET

    def get_odds(self, match_id: str) -> MarketOdds:
        if match_id not in self.registry:
            raise PolymarketError(f"Polymarket registry 中无 {match_id} 的映射(slug/队名)")
        slug, mapping = self.registry[match_id]
        event = self.client.get_event_by_slug(slug)
        return event_to_market_odds(event, match_id, mapping)
