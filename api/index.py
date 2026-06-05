"""Vercel/WSGI 入口：把世界杯分析系统暴露成零依赖的 JSON API。

为何这样设计（适配 serverless 限制）：
- 纯标准库 WSGI app（变量名 `app`），无需 Flask/FastAPI 等依赖。
- 重计算（历史比分校准 ~3s）已**预计算**并打包为 data/calibrated_groups.json，
  请求时只跑快速的"模拟 + 向盘口收缩 + 价值扫描"，避免函数超时。
- 历史数据缓存在只读 FS 下自动回退到 /tmp。

路由：
  GET /                      系统说明(HTML)
  GET /api/health            健康检查
  GET /api/outright          真实 Polymarket 夺冠盘去抽水概率
  GET /api/value?weight=&sims=  模拟→收缩→价值扫描(用预计算评分)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs

# 让 src/ 下的包可被导入（Vercel 上本包未安装）
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from worldcup_betting.config import RiskConfig  # noqa: E402
from worldcup_betting.tools.blending import blend_beliefs  # noqa: E402
from worldcup_betting.tools.calibration import dataset_name  # noqa: E402
from worldcup_betting.tools.outright import scan_outright_value  # noqa: E402
from worldcup_betting.tools.polymarket import (  # noqa: E402
    PolymarketClient,
    PolymarketError,
    event_to_outright_probs,
)
from worldcup_betting.tools.tournament import championship_probabilities  # noqa: E402
from worldcup_betting.tools.wc2026_data import calibrated_groups_or_default  # noqa: E402

_INDEX_HTML = """<!doctype html><html lang=zh><meta charset=utf-8>
<title>世界杯多智能体赛事分析</title>
<style>body{font-family:system-ui,Arial;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.6}
code{background:#f3f3f3;padding:2px 6px;border-radius:4px}a{color:#0a58ca}</style>
<h1>⚽ 世界杯多智能体赛事分析系统</h1>
<p>仅供研究参考，不构成投注建议。数据源：Polymarket 夺冠盘 + 历史比分校准模拟。</p>
<h2>API</h2>
<ul>
<li><code>GET <a href="/api/health">/api/health</a></code> — 健康检查</li>
<li><code>GET <a href="/api/outright">/api/outright</a></code> — 真实夺冠盘去抽水概率</li>
<li><code>GET <a href="/api/value?weight=0.35&sims=4000">/api/value?weight=0.35&sims=4000</a></code>
 — 校准模拟 → 向盘口收缩 → 价值扫描</li>
</ul>
<p>⚠ 模型存在已知偏差(弱洲高估、单场方差压平大热门)，收缩后仅供研究。</p>
</html>"""


def _json(start, data, status="200 OK"):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    start(status, [("Content-Type", "application/json; charset=utf-8"),
                   ("Content-Length", str(len(body))),
                   ("Cache-Control", "public, max-age=60")])
    return [body]


def _outright_rows():
    ev = PolymarketClient().get_event_by_slug("world-cup-winner")
    return event_to_outright_probs(ev)


def _handle_outright(start):
    rows = _outright_rows()
    return _json(start, {
        "source": "polymarket:world-cup-winner",
        "teams": [{"team": r["team"], "market_prob": round(r["fair_prob"], 4),
                   "decimal_odds": round(r["decimal_odds"], 2),
                   "liquidity": round(r["liquidity"], 0)} for r in rows[:30]],
    })


def _handle_value(start, qs):
    weight = float(qs.get("weight", ["0.35"])[0])
    sims = min(int(qs.get("sims", ["4000"])[0]), 20000)  # 上限防超时

    cgroups = calibrated_groups_or_default()
    sim = championship_probabilities(cgroups, n_sims=sims)
    model = {dataset_name(t): p for t, p in sim.probabilities.items()}

    rows = _outright_rows()
    market = {dataset_name(str(r["team"])): r["fair_prob"] for r in rows}
    blended = blend_beliefs(model, market, weight=weight)
    norm_to_team = {dataset_name(str(r["team"])): str(r["team"]) for r in rows}
    beliefs = {norm_to_team[k]: v for k, v in blended.items() if k in norm_to_team}

    cfg = RiskConfig(min_market_prob=0.02)
    opps = scan_outright_value(rows, beliefs, cfg)
    values = [o for o in opps if o.is_value]
    return _json(start, {
        "params": {"weight": weight, "sims": sims},
        "value_bets": [{"team": o.team, "model_prob": round(model.get(dataset_name(o.team), 0), 4),
                        "market_prob": round(o.market_prob, 4), "blended_prob": round(o.user_prob, 4),
                        "edge": round(o.edge, 4), "stake_fraction": round(o.stake_fraction, 4)}
                       for o in values],
        "disclaimer": "仅供研究参考，模型有已知偏差，勿据此下注。",
    })


def app(environ, start_response):
    """WSGI 入口。"""
    path = environ.get("PATH_INFO", "/")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    try:
        if path in ("/", "/index.html"):
            body = _INDEX_HTML.encode("utf-8")
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                      ("Content-Length", str(len(body)))])
            return [body]
        if path == "/api/health":
            return _json(start_response, {"status": "ok"})
        if path == "/api/outright":
            return _handle_outright(start_response)
        if path == "/api/value":
            return _handle_value(start_response, qs)
        return _json(start_response, {"error": "not found", "path": path}, "404 Not Found")
    except PolymarketError as e:
        return _json(start_response, {"error": "polymarket", "detail": str(e)}, "502 Bad Gateway")
    except Exception as e:  # noqa: BLE001 — 兜底，返回 JSON 而非 500 堆栈
        return _json(start_response, {"error": "internal", "detail": str(e)}, "500 Internal Server Error")


# 本地自测：python api/index.py  → http://localhost:8000
if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    print("serving on http://localhost:8000")
    make_server("localhost", 8000, app).serve_forever()
