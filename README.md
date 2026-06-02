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

## 接真实数据

`tools/match_data.py` 与 `tools/odds_providers.py` 中的 Provider 已抽象为接口，
接实盘只需新增实现：

- **体彩**：解析竞彩足球胜平负固定赔率
- **Polymarket**：经 Gamma/CLOB API 读取 outcome 价格（`1/price` 转十进制赔率）
- **赛事数据**：API-Football / FotMob 等补充 xG、阵容等特征

## 合规声明

系统仅做分析推荐，不提供自动下注、不规避任何平台限制。中国大陆仅体彩为合法体育彩票，
Polymarket 等在部分法域受限，使用者须遵守所在地法律法规。
