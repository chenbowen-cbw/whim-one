# 世界杯多智能体赛事分析系统 ⚽🤖

基于 **Python + Claude Agent SDK** 的多智能体赛事分析与**价值投注推荐**系统，
支持对接**体彩**与 **Polymarket** 盘口。

> ⚠️ **仅做分析与推荐，不自动下注。** 是否投注、在何处投注由你自行决定并承担合规与资金风险。
> 任何模型都不保证盈利，请理性投注、量力而行。

## 它能做什么

1. 采集赛事数据（实力、近期状态、伤停）
2. 聚合体彩 + Polymarket 盘口，统一为十进制赔率并**去水位**得到无抽水隐含概率
3. 用模型估计胜平负**真实概率**（基线模型 / LLM 多智能体两条路径）
4. 跨盘口扫描**价值投注**（正期望 edge）
5. 经四道风控闸（价值阈值 / 分数凯利 / 单注上限 / 组合敞口上限）产出**金额建议**

核心理念：**LLM 负责软判断（估概率、读盘口），确定性代码负责硬计算（去水位、EV、凯利、敞口）。**
钱怎么下永远由可测试的代码决定，不被模型幻觉左右。

## 快速开始

```bash
# 1. 确定性路径：无需任何 API Key，离线即可端到端跑通
python examples/analyze_match.py

# 2. 多智能体路径：用 Claude Agent SDK（需 API Key 与 claude-agent-sdk）
pip install claude-agent-sdk
ANTHROPIC_API_KEY=sk-ant-... python examples/analyze_match.py --agents

# 3. 跑测试（确定性内核全覆盖）
pip install pytest && python -m pytest -q
```

### 示例输出

```
赛事分析报告  阿根廷 vs 墨西哥  (group)
[模型预测]  (置信度 45%)
  主胜: 75.4%   平局: 12.4%   客胜: 12.2%
[盘口对比]  (去水位隐含概率)
  sporttery   | 主胜 1.55/61%  平局 3.90/24%  客胜 6.50/15% | 抽水 +5.5%
  polymarket  | 主胜 1.67/62%  平局 4.17/25%  客胜 7.69/13% | 抽水 -3.0%
[投注推荐]
  ▶ polymarket 押 主胜 @ 1.67 | EV +25.7% | 建议 5.0% 资金 (≈500)
  ▶ sporttery 押 主胜 @ 1.55 | EV +16.9% | 建议 5.0% 资金 (≈500)
```

## 架构一览

```
协调智能体 Orchestrator
 ├─ 数据采集 DataCollector  (get_match)
 ├─ 盘口聚合 OddsAggregator (get_odds：体彩/Polymarket 去水位对比)
 ├─ 赛事分析 MatchAnalyst   (baseline_prediction → 校准真实概率)
 ├─ 价值投注 ValueBetting   (evaluate_value_bets：edge/凯利)
 └─ 风控     RiskManager    (置信度/敞口复核 + 风险提示)
                  ▼
        确定性风控内核 → 投注推荐
```

完整设计、数据流、数学公式与路线图见 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**。

## 目录结构

```
src/worldcup_betting/
├── models.py             数据模型
├── config.py             风控参数 / 运行开关
├── tools/analytics.py    纯数学内核（赔率/EV/凯利/价值扫描）★ 单测覆盖
├── tools/baseline_model.py 确定性基线预测器（降级路径 & 对照基准）
├── tools/match_data.py   赛事数据 Provider（接口 + Mock）
├── tools/odds_providers.py 体彩 / Polymarket Provider（接口 + Mock）
├── risk.py               风控内核：价值 → 投注建议
├── orchestrator.py       编排（确定性 & 智能体共用出口）
├── sdk_tools.py          能力 → Claude Agent SDK MCP 工具
└── agents/               智能体定义与运行器
examples/analyze_match.py 主流程示例（带报告打印）
tests/test_analytics.py   单元测试
```

## 赛制蒙特卡洛夺冠模拟

把整届世界杯按真实赛制（48队/12组，前2+最佳8个第3 → 淘汰赛）打上万遍，
统计各队夺冠频率，作为**独立于盘口**的概率观点，替代简陋的幂变换基线：

```bash
python examples/tournament_sim.py        # 模拟 + 对比真实盘口 + 价值扫描
```

- `tools/tournament.py`：泊松进球模型 → 小组赛名次 → 出线 → 淘汰赛（含点球）→ 冠军
- 输出 `{队名: 夺冠概率}`，**接口与基线一致**，下游价值扫描/凯利/风控零改动
- 10000 届约 2 秒，可复现（带 seed）

### 向盘口收缩（以市场为先验）

```bash
python examples/blended_value.py --weight 0.35   # 校准→模拟→收缩→价值扫描 全闭环
```

校准模型仍有系统性偏差，直接算 edge 会冒出"押新西兰 +300%"的假信号。
`tools/blending.py` 用**对数线性池**把模型概率向盘口收缩：

```
p_blend ∝ p_market^(1-λ) · p_model^λ     即 log(p_blend/p_market) = λ·log(p_model/p_market)
λ=0 纯盘口(零观点) … λ=1 纯模型；0<λ<1 受控偏离
```

再配一道 `min_market_prob` 风控闸（默认关，示例设 2%）：**市场都不当回事的极端冷门不碰**
（模型在弱队上不可信，长赔率还含冷门溢价）。两者叠加后输出变得克制可用：

```
λ=0.35  →  ✅Netherlands +18.3% 下0.2%   ✅Germany +11.2% 下0.2%
           (新西兰/乌兹别克等冷门 +300% 假信号被市场概率闸全部否决，透明保留可审计)
```

从"押新西兰夺冠 +300%"到"荷兰德国略被低估、各 0.2% 仓位"——这才是可用的输出。

### 实力评分校准（历史比分最大似然）

```bash
python examples/calibrate.py     # 拉取真实历史比分→拟合评分→重跑模拟→对比盘口
```

- 数据源：martj42/international_results（1872 至今全部国际A级赛，CC0），首次自动下载缓存
- `tools/calibration.py`：纯 Python 梯度上升拟合各队 power + 主场优势，**拟合模型与模拟器
  进球公式完全同构**，评分可直接喂回模拟器
- `tools/historical_data.py`：按"赛事重要性 × 时间衰减(半衰期7年)"给每场比赛加权

拟合结果合理（西班牙/英格兰/比利时居前，home_adv≈0.22，圣马力诺等鱼腩为负），但**诚实地
保留两处已知差距**：① 纯比分模型高估弱洲强队（未充分校正洲际赛程强弱）；② 单场淘汰 +
泊松方差大，压平大热门、夺冠概率系统性低于盘口。下一步：洲际强度校正 / 降方差 / 以盘口为先验。

## 回测与策略验证

```bash
python examples/backtest_demo.py --sweep
```

- **回测引擎**（`backtest/engine.py`）：bankroll 逐笔复利演进，统计 ROI/命中率/最大回撤；
  线上线下用**同一套**去抽水→修正→凯利逻辑，避免行为漂移。
- **蒙特卡洛验证**（`backtest/montecarlo.py`）：2026 世界杯尚未开赛、无真实赛果，
  故显式建模"市场 = 真实概率 + 热门冷门偏差(beta) + 抽水(overround)"，
  让策略在不知真相下博弈，跑上千届看 ROI 分布——这是无历史数据时最严谨的验证。

盈利边界扫描（真实跑出，gamma=1.20）：

```
  beta  抽水   平均增长  盈利占比   ROI
  1.00   3%    -1.6%     44%    -3.2%   ← 无偏差：被抽水吃成负EV
  1.25   3%    +2.6%     66%    +6.0%
  1.40   3%    +3.8%     73%   +11.4%   ← 偏差越强、抽水越低越赚
  1.40   8%    +0.0%      0%    +0.0%   ← 高抽水下克制不下注，保本
```

诚实结论：**价值只来自你的概率优于市场（此处由偏差建模），不来自盘口本身；
高抽水会吞掉 edge。** 真实盈利还需扣除滑点与税费。

## 真实数据源

**Polymarket 已接入真实数据**（`tools/polymarket.py`，Gamma API，公开免鉴权）：

```bash
python examples/polymarket_live.py            # 真实夺冠盘概率排行
python examples/polymarket_live.py --list     # 列出对阵/世界杯赛事
python examples/polymarket_live.py --slug <event-slug> --home "队A" --away "队B"  # 逐场1X2
```

实测输出（真实行情）：

```
【世界杯夺冠盘 · 真实 Polymarket 行情】 48 队
  France      16.6%   赔率 5.87   流动性 $877,110
  Spain       15.9%   赔率 6.12   流动性 $921,041
  Argentina    8.5%   赔率 11.43  流动性 $1,352,519
```

- 价格(0~1)即隐含概率，按 `1/price` 转十进制赔率，与体彩同坐标系比较。
- 同时抓取 `liquidity`/`spread` 作为风控信号（写入 `MarketOdds.metadata`）。
- 支持两种盘口形式：单一三选市场、negRisk 分组的三个二元市场。
- 逐场胜平负市场通常临近开赛才开盘；未开盘时用夺冠盘演示真实数据流，且会优雅报错提示可用选项。

### 真实价值扫描（夺冠盘）

给出你对某队夺冠概率的判断，系统对比真实盘口算 edge/凯利，并用真实流动性做风控：

```bash
python examples/outright_value.py --bet Argentina=0.15 --bet Brazil=0.12 --bet France=0.14
```

实测输出（真实行情）：

```
[✅ 价值] Argentina  你的判断 15.0% vs 盘口隐含 8.5% (赔率 11.43)
         edge +71.4%  ▶ 建议下注 1.7% 资金 ≈ $171
[—  跳过] France     你的判断 14.0% vs 盘口隐含 16.6%  edge -17.9% 未达阈值
```

系统只负责去抽水、算 edge/凯利、用真实流动性与四道风控闸过滤、给金额；
概率判断与最终决策由你负责。

其余数据源仍为接口 + Mock，接实盘只需新增实现：

- **体彩**：解析竞彩足球胜平负固定赔率（官方无公开 API，需抓页面，注意合规与频率）
- **赛事数据**：API-Football / FotMob / football-data.org 补充 xG、阵容等特征

## 合规声明

系统仅做分析推荐，不提供自动下注、不规避任何平台限制。中国大陆仅体彩为合法体育彩票，
Polymarket 等在部分法域受限，使用者须遵守所在地法律法规。
