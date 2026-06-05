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

_INDEX_HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>世界杯赛事分析 · 价值投注研究</title>
<style>
  :root{--bg:#0b1020;--card:#151b2e;--line:#26304a;--fg:#e8ecf5;--mut:#9aa6c0;
        --grn:#2ecc71;--red:#ff5d5d;--accent:#5b8cff;--chip:#1e2740}
  *{box-sizing:border-box}
  body{margin:0;background:linear-gradient(180deg,#0b1020,#0d1428);color:var(--fg);
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",Arial;
       line-height:1.55}
  .wrap{max-width:920px;margin:0 auto;padding:28px 18px 60px}
  header h1{margin:0 0 6px;font-size:24px}
  .sub{color:var(--mut);font-size:14px}
  .disc{margin:14px 0;padding:10px 14px;background:#2a1d16;border:1px solid #5a3b22;
        border-radius:10px;color:#ffcaa6;font-size:13px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
        padding:18px;margin:16px 0;box-shadow:0 6px 24px rgba(0,0,0,.25)}
  .card h2{margin:0 0 12px;font-size:17px;display:flex;align-items:center;gap:8px}
  .card h2 .tag{font-size:11px;color:var(--mut);font-weight:400;background:var(--chip);
        padding:2px 8px;border-radius:20px}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  th{color:var(--mut);font-weight:500;font-size:12px;position:sticky;top:0}
  tr.value{background:rgba(46,204,113,.08)}
  tr.value td:first-child::before{content:"✅ ";}
  .pos{color:var(--grn)}.neg{color:var(--red)}
  .controls{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-end}
  .ctl{display:flex;flex-direction:column;gap:6px}
  .ctl label{font-size:12px;color:var(--mut)}
  .ctl input[type=range]{width:200px;accent-color:var(--accent)}
  .ctl input[type=number]{width:110px;background:#0e1426;border:1px solid var(--line);
        color:var(--fg);border-radius:8px;padding:7px 9px;font-size:14px}
  .lamval{font-variant-numeric:tabular-nums;color:var(--fg);font-size:13px}
  button{background:var(--accent);color:#fff;border:0;border-radius:10px;
        padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer}
  button:disabled{opacity:.55;cursor:progress}
  .summary{margin:12px 0 4px;font-size:14px;color:var(--mut)}
  .summary b{color:var(--fg)}
  .muted{color:var(--mut);font-size:13px}
  .err{color:var(--red);font-size:13px}
  .bar{display:inline-block;height:8px;border-radius:4px;background:var(--accent);vertical-align:middle}
  footer{margin-top:26px;color:var(--mut);font-size:12px;line-height:1.7}
  a{color:var(--accent)}
  .spin{display:inline-block;width:14px;height:14px;border:2px solid var(--mut);
        border-top-color:transparent;border-radius:50%;animation:s .7s linear infinite;vertical-align:-2px}
  @keyframes s{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>⚽ 世界杯赛事分析 · 价值投注研究</h1>
    <div class="sub">真实 Polymarket 夺冠盘 + 历史比分校准的赛制蒙特卡洛模拟 + 向盘口收缩</div>
  </header>
  <div class="disc">⚠ 仅供研究与学习参考，<b>不构成投注建议</b>。模型存在已知偏差（弱洲高估、单场方差压平大热门），
    所有结果经向市场收缩后仍仅供研究。是否投注由你自行决定并自负合规与资金风险，请理性投注、量力而行。</div>

  <div class="card">
    <h2>夺冠盘真实行情 <span class="tag">Polymarket · 去抽水隐含概率</span></h2>
    <div id="market-status" class="muted"><span class="spin"></span> 正在拉取真实行情…</div>
    <table id="market-table" hidden>
      <thead><tr><th>球队</th><th>夺冠概率</th><th>赔率</th><th>流动性($)</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="card">
    <h2>价值分析参数</h2>
    <div class="controls">
      <div class="ctl">
        <label>对模型的信任度 λ <span class="lamval" id="lamval">0.35</span></label>
        <input type="range" id="weight" min="0" max="1" step="0.05" value="0.35">
        <span class="muted" style="font-size:11px">0 = 完全信盘口（零观点）· 1 = 完全信模型</span>
      </div>
      <div class="ctl">
        <label>模拟届数</label>
        <input type="number" id="sims" min="1000" max="20000" step="1000" value="4000">
      </div>
      <div class="ctl">
        <button id="run">运行价值分析</button>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>模型 vs 盘口 · 收缩后价值 <span class="tag">✅ 行=通过四道风控的价值机会</span></h2>
    <div id="value-status" class="muted">点击上方「运行价值分析」开始（首次约需数秒：模拟 + 拉盘口）。</div>
    <div id="value-summary" class="summary" hidden></div>
    <table id="value-table" hidden>
      <thead><tr><th>球队</th><th>模型</th><th>盘口</th><th>收缩后</th><th>edge</th><th>建议仓位</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <footer>
    数据：<a href="https://polymarket.com" target="_blank" rel="noopener">Polymarket</a> 夺冠盘 ·
    历史比分 martj42/international_results · 评分经泊松最大似然校准（预计算）。<br>
    方法：去抽水隐含概率 → 校准赛制蒙特卡洛模拟夺冠概率 → 对数线性池向盘口收缩(λ) →
    edge/凯利 → 四道风控（价值阈值/分数凯利/单注上限/组合敞口/流动性/极端冷门）。<br>
    API：<a href="/api/outright">/api/outright</a> · <a href="/api/value?weight=0.35&sims=4000">/api/value</a>
  </footer>
</div>

<script>
const CN = {
  "France":"法国","Spain":"西班牙","England":"英格兰","Portugal":"葡萄牙","Argentina":"阿根廷",
  "Brazil":"巴西","Germany":"德国","Netherlands":"荷兰","Norway":"挪威","Belgium":"比利时",
  "Japan":"日本","Colombia":"哥伦比亚","Mexico":"墨西哥","Morocco":"摩洛哥","Turkiye":"土耳其",
  "Turkey":"土耳其","USA":"美国","United States":"美国","Uruguay":"乌拉圭","Switzerland":"瑞士",
  "Ecuador":"厄瓜多尔","Croatia":"克罗地亚","Senegal":"塞内加尔","Ivory Coast":"科特迪瓦",
  "Austria":"奥地利","Sweden":"瑞典","Canada":"加拿大","South Korea":"韩国","Ghana":"加纳",
  "Bosnia-Herzegovina":"波黑","Paraguay":"巴拉圭","Scotland":"苏格兰","Italy":"意大利",
  "Denmark":"丹麦","Serbia":"塞尔维亚","Algeria":"阿尔及利亚","Iran":"伊朗","Australia":"澳大利亚",
  "Nigeria":"尼日利亚","Peru":"秘鲁","New Zealand":"新西兰","Egypt":"埃及","Uzbekistan":"乌兹别克斯坦",
  "Tunisia":"突尼斯","Qatar":"卡塔尔","Jordan":"约旦","Panama":"巴拿马","Saudi Arabia":"沙特阿拉伯",
  "Curacao":"库拉索","Curaçao":"库拉索","Haiti":"海地","Cape Verde":"佛得角","Jamaica":"牙买加",
  "Honduras":"洪都拉斯","Poland":"波兰","Ukraine":"乌克兰","Wales":"威尔士","Greece":"希腊",
  "Czechia":"捷克","Romania":"罗马尼亚","Hungary":"匈牙利","Cameroon":"喀麦隆","Mali":"马里",
  "South Africa":"南非","Venezuela":"委内瑞拉","Chile":"智利","Costa Rica":"哥斯达黎加"
};
const cn = t => CN[t] || t;
const pct = x => (x*100).toFixed(1) + '%';
const signed = x => (x>=0?'+':'') + (x*100).toFixed(1) + '%';
const fmt = n => n>=1000 ? (n/1000).toFixed(0)+'k' : (''+Math.round(n));

async function loadMarket(){
  const st = document.getElementById('market-status');
  try{
    const r = await fetch('/api/outright'); const d = await r.json();
    if(d.error){ st.className='err'; st.textContent='行情拉取失败：'+(d.detail||d.error); return; }
    const tb = document.querySelector('#market-table tbody'); tb.innerHTML='';
    const max = Math.max(...d.teams.map(t=>t.market_prob));
    d.teams.slice(0,16).forEach(t=>{
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${cn(t.team)}</td><td>${pct(t.market_prob)}
        <span class="bar" style="width:${Math.round(t.market_prob/max*60)}px"></span></td>
        <td>${t.decimal_odds.toFixed(2)}</td><td>$${fmt(t.liquidity)}</td>`;
      tb.appendChild(tr);
    });
    st.hidden=true; document.getElementById('market-table').hidden=false;
  }catch(e){ st.className='err'; st.textContent='网络错误：'+e.message; }
}

async function runValue(){
  const btn=document.getElementById('run'), st=document.getElementById('value-status');
  const sum=document.getElementById('value-summary'), tbl=document.getElementById('value-table');
  const w=document.getElementById('weight').value, sims=document.getElementById('sims').value;
  btn.disabled=true; tbl.hidden=true; sum.hidden=true;
  st.hidden=false; st.className='muted'; st.innerHTML='<span class="spin"></span> 模拟中（λ='+w+'，'+sims+' 届）…';
  try{
    const r=await fetch(`/api/value?weight=${w}&sims=${sims}`); const d=await r.json();
    if(d.error){ st.className='err'; st.textContent='分析失败：'+(d.detail||d.error); btn.disabled=false; return; }
    const tb=tbl.querySelector('tbody'); tb.innerHTML='';
    d.comparison.forEach(o=>{
      const tr=document.createElement('tr'); if(o.is_value) tr.className='value';
      const ec = o.edge>=0?'pos':'neg';
      tr.innerHTML=`<td>${cn(o.team)}</td><td>${pct(o.model_prob)}</td><td>${pct(o.market_prob)}</td>
        <td>${pct(o.blended_prob)}</td><td class="${ec}">${signed(o.edge)}</td>
        <td>${o.is_value? pct(o.stake_fraction) : '—'}</td>`;
      tb.appendChild(tr);
    });
    sum.hidden=false;
    sum.innerHTML=`价值机会 <b>${d.value_count}</b> 个 · 合计建议敞口 <b>${pct(d.total_stake_fraction)}</b> 资金`
      + (d.value_count===0 ? ' · 当前 λ 下无满足风控的机会（更保守=更可信）' : '');
    st.hidden=true; tbl.hidden=false;
  }catch(e){ st.className='err'; st.textContent='网络错误：'+e.message; }
  btn.disabled=false;
}

document.getElementById('weight').addEventListener('input',e=>{
  document.getElementById('lamval').textContent=(+e.target.value).toFixed(2);
});
document.getElementById('run').addEventListener('click',runValue);
loadMarket();
</script>
</body>
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

    # 对比表：按盘口概率取前若干强队，展示 模型/盘口/收缩后/edge
    comparison = sorted(opps, key=lambda o: o.market_prob, reverse=True)[:16]
    return _json(start, {
        "params": {"weight": weight, "sims": sims},
        "value_count": len(values),
        "total_stake_fraction": round(sum(o.stake_fraction for o in values), 4),
        "comparison": [{"team": o.team,
                        "model_prob": round(model.get(dataset_name(o.team), 0), 4),
                        "market_prob": round(o.market_prob, 4),
                        "blended_prob": round(o.user_prob, 4),
                        "edge": round(o.edge, 4),
                        "stake_fraction": round(o.stake_fraction, 4),
                        "is_value": o.is_value} for o in comparison],
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
