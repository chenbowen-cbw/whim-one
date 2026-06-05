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
  .verdict{font-size:15px;padding:12px 14px;border-radius:10px;margin-bottom:14px;
        background:#16233a;border:1px solid #2c456e;line-height:1.6}
  .bet{background:#13231a;border:1px solid #265a3a;border-radius:12px;padding:14px 16px;margin:10px 0}
  .bet .top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}
  .bet .team{font-size:18px;font-weight:700}
  .bet .amt{font-size:18px;font-weight:700;color:var(--grn)}
  .bet .why{color:var(--mut);font-size:13px;margin-top:8px;line-height:1.6}
  .bet .how{margin-top:8px;font-size:13px}
  .bet .how a{font-weight:600}
  .nobet{background:#23201a;border:1px solid #5a4a22;border-radius:12px;padding:16px;color:#ffe0b0}
  .field{display:flex;flex-direction:column;gap:6px}
  .field label{font-size:13px;color:var(--mut)}
  .field input,.field select{background:#0e1426;border:1px solid var(--line);color:var(--fg);
        border-radius:8px;padding:9px 11px;font-size:15px;min-width:130px}
  details{margin-top:14px}
  details summary{cursor:pointer;color:var(--mut);font-size:13px;user-select:none}
  .big{font-size:15px;padding:11px 22px}
  .step{font-size:12px;color:var(--accent);font-weight:600;letter-spacing:.5px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>⚽ 世界杯夺冠 · 该不该买、买哪个</h1>
    <div class="sub">用真实赔率 + 数据模型，帮你判断哪支球队"性价比"略高。仅供参考。</div>
  </header>
  <div class="disc">⚠ <b>这不是稳赚的攻略，是研究工具</b>。模型并不完美，多数时候它会告诉你"没什么便宜可捡，建议别买"——
    这恰恰是诚实的。买不买、买多少由你自己决定，赌博有风险，可能血本无归，请量力而行、遵守当地法律。</div>

  <div class="card">
    <h2><span class="step">第 1 步</span>　各队夺冠"行情" <span class="tag">来自真实交易市场 Polymarket</span></h2>
    <div class="muted" style="font-size:13px;margin-bottom:8px">下面是市场现在认为各队夺冠的概率和赔率。赔率越高=越不被看好=赌中赔得越多。</div>
    <div id="market-status" class="muted"><span class="spin"></span> 正在拉取真实行情…</div>
    <table id="market-table" hidden>
      <thead><tr><th>球队</th><th>市场认为的夺冠概率</th><th>赔率(押1赢回)</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="card">
    <h2><span class="step">第 2 步</span>　让系统帮你算</h2>
    <div class="controls">
      <div class="field">
        <label>你打算最多投入多少钱？</label>
        <input type="number" id="bankroll" min="1" step="100" value="1000">
      </div>
      <div class="field">
        <label>风格</label>
        <select id="style">
          <option value="0.25">保守（更信市场，建议更少）</option>
          <option value="0.35" selected>平衡（推荐）</option>
          <option value="0.55">大胆（更信模型，建议更多）</option>
        </select>
      </div>
      <div class="field">
        <label>&nbsp;</label>
        <button id="run" class="big">开始分析</button>
      </div>
    </div>
  </div>

  <div class="card">
    <h2><span class="step">第 3 步</span>　系统给你的结论</h2>
    <div id="value-status" class="muted">填好上面，点「开始分析」（首次约需几秒：要跑几千次模拟 + 拉实时盘口）。</div>
    <div id="verdict" class="verdict" hidden></div>
    <div id="bets"></div>
    <details id="detail" hidden>
      <summary>查看完整数据（进阶 / 给懂行的人看）</summary>
      <table id="value-table" style="margin-top:10px">
        <thead><tr><th>球队</th><th>模型概率</th><th>市场概率</th><th>修正后</th><th>edge</th><th>建议仓位</th></tr></thead>
        <tbody></tbody>
      </table>
    </details>
  </div>

  <footer>
    <b>怎么理解：</b>系统先用近十年真实比分校准各队实力，再把整届世界杯模拟几千遍算出"模型认为的夺冠概率"，
    然后和市场赔率对比。只有当"模型概率明显高于市场定价"时，才算一次<b>可能划算</b>的下注，并据此算出一个很保守的建议金额。<br>
    数据：<a href="https://polymarket.com" target="_blank" rel="noopener">Polymarket</a> 真实盘口 + 历史国际比赛比分。
    多数情况下市场定价合理、没什么便宜可捡——那时系统会直接建议你观望。<br>
    <span class="muted">进阶接口：<a href="/api/outright">/api/outright</a> · <a href="/api/value?weight=0.35&sims=4000">/api/value</a></span>
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

const money = n => '¥' + (Math.round(n*100)/100).toLocaleString('zh-CN');

async function loadMarket(){
  const st = document.getElementById('market-status');
  try{
    const r = await fetch('/api/outright'); const d = await r.json();
    if(d.error){ st.className='err'; st.textContent='行情拉取失败：'+(d.detail||d.error); return; }
    const tb = document.querySelector('#market-table tbody'); tb.innerHTML='';
    const max = Math.max(...d.teams.map(t=>t.market_prob));
    d.teams.slice(0,12).forEach(t=>{
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${cn(t.team)}</td><td>${pct(t.market_prob)}
        <span class="bar" style="width:${Math.round(t.market_prob/max*70)}px"></span></td>
        <td>${t.decimal_odds.toFixed(1)} 倍</td>`;
      tb.appendChild(tr);
    });
    st.hidden=true; document.getElementById('market-table').hidden=false;
  }catch(e){ st.className='err'; st.textContent='网络错误：'+e.message; }
}

function betCard(o){
  const profit = o.stake_amount * (o.decimal_odds - 1);
  return `<div class="bet">
    <div class="top"><span class="team">买 ${cn(o.team)} 夺冠</span>
      <span class="amt">建议投 ${money(o.stake_amount)}</span></div>
    <div class="why">为什么：系统模型估它夺冠概率约 <b>${pct(o.model_prob)}</b>，
      而市场现在只定价 <b>${pct(o.market_prob)}</b>，所以理论上略微"便宜"了一点。<br>
      若押 ${money(o.stake_amount)} 赌中（赔率 ${o.decimal_odds.toFixed(1)} 倍），可赢回约 ${money(o.stake_amount*o.decimal_odds)}（净赚约 ${money(profit)}）；没中则亏掉这 ${money(o.stake_amount)}。</div>
    <div class="how">怎么买：去 <a href="https://polymarket.com" target="_blank" rel="noopener">Polymarket</a>
      搜「World Cup Winner」→ 找到 ${cn(o.team)} → 买「Yes」。</div>
  </div>`;
}

async function runValue(){
  const btn=document.getElementById('run'), st=document.getElementById('value-status');
  const verdict=document.getElementById('verdict'), bets=document.getElementById('bets');
  const detail=document.getElementById('detail');
  const w=document.getElementById('style').value;
  const bankroll=Math.max(1, +document.getElementById('bankroll').value||1000);
  btn.disabled=true; verdict.hidden=true; bets.innerHTML=''; detail.hidden=true;
  st.hidden=false; st.className='muted'; st.innerHTML='<span class="spin"></span> 正在模拟几千届世界杯并对比实时盘口…';
  try{
    const r=await fetch(`/api/value?weight=${w}&sims=4000&bankroll=${bankroll}`); const d=await r.json();
    if(d.error){ st.className='err'; st.textContent='分析失败，请稍后重试：'+(d.detail||d.error); btn.disabled=false; return; }
    st.hidden=true;
    if(d.value_count===0){
      verdict.hidden=false;
      verdict.innerHTML='🟡 <b>本次结论：建议观望，先别买。</b><br>'+
        '系统没找到"明显划算"的下注——目前市场把各队的赔率定得挺合理，没什么便宜可捡。'+
        '这是很正常的结果，硬买大概率只是给平台交手续费。';
    }else{
      verdict.hidden=false;
      verdict.innerHTML='🟢 <b>本次结论：发现 '+d.value_count+' 个"可能略划算"的标的</b>，'+
        '合计建议投入 <b>'+money(d.total_stake_amount)+'</b>（约占你预算的 '+pct(d.total_stake_fraction)+'）。'+
        '注意金额都很小——因为优势很薄，重注不明智。';
      bets.innerHTML=d.value_bets.map(betCard).join('');
    }
    // 进阶折叠表
    const tb=document.querySelector('#value-table tbody'); tb.innerHTML='';
    d.comparison.forEach(o=>{
      const tr=document.createElement('tr'); if(o.is_value) tr.className='value';
      const ec=o.edge>=0?'pos':'neg';
      tr.innerHTML=`<td>${cn(o.team)}</td><td>${pct(o.model_prob)}</td><td>${pct(o.market_prob)}</td>
        <td>${pct(o.blended_prob)}</td><td class="${ec}">${signed(o.edge)}</td>
        <td>${o.is_value? pct(o.stake_fraction) : '—'}</td>`;
      tb.appendChild(tr);
    });
    detail.hidden=false;
  }catch(e){ st.className='err'; st.textContent='网络错误：'+e.message; }
  btn.disabled=false;
}

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
    bankroll = max(1.0, float(qs.get("bankroll", ["1000"])[0]))

    cgroups = calibrated_groups_or_default()
    sim = championship_probabilities(cgroups, n_sims=sims)
    model = {dataset_name(t): p for t, p in sim.probabilities.items()}

    rows = _outright_rows()
    market = {dataset_name(str(r["team"])): r["fair_prob"] for r in rows}
    blended = blend_beliefs(model, market, weight=weight)
    norm_to_team = {dataset_name(str(r["team"])): str(r["team"]) for r in rows}
    beliefs = {norm_to_team[k]: v for k, v in blended.items() if k in norm_to_team}

    cfg = RiskConfig(bankroll=bankroll, min_market_prob=0.02)
    opps = scan_outright_value(rows, beliefs, cfg)
    values = [o for o in opps if o.is_value]

    # 对比表：按盘口概率取前若干强队，展示 模型/盘口/收缩后/edge
    comparison = sorted(opps, key=lambda o: o.market_prob, reverse=True)[:16]
    return _json(start, {
        "params": {"weight": weight, "sims": sims, "bankroll": bankroll},
        "value_count": len(values),
        "total_stake_fraction": round(sum(o.stake_fraction for o in values), 4),
        "total_stake_amount": round(sum(o.stake_amount for o in values), 2),
        "comparison": [{"team": o.team,
                        "model_prob": round(model.get(dataset_name(o.team), 0), 4),
                        "market_prob": round(o.market_prob, 4),
                        "blended_prob": round(o.user_prob, 4),
                        "edge": round(o.edge, 4),
                        "decimal_odds": round(o.decimal_odds, 2),
                        "stake_fraction": round(o.stake_fraction, 4),
                        "stake_amount": round(o.stake_amount, 2),
                        "is_value": o.is_value} for o in comparison],
        "value_bets": [{"team": o.team, "model_prob": round(model.get(dataset_name(o.team), 0), 4),
                        "market_prob": round(o.market_prob, 4), "blended_prob": round(o.user_prob, 4),
                        "edge": round(o.edge, 4), "decimal_odds": round(o.decimal_odds, 2),
                        "stake_fraction": round(o.stake_fraction, 4),
                        "stake_amount": round(o.stake_amount, 2)}
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
