# 世界杯多智能体赛事分析系统 — 架构设计

> 定位：**赛事分析 + 价值投注推荐**的决策支持系统。系统不自动下注，最终是否投注、
> 在何处投注由用户自行决定并承担合规与资金风险。

## 1. 设计目标与原则

| 目标 | 做法 |
| --- | --- |
| 可解释 | 每条建议都附带"模型概率 vs 盘口隐含概率 vs edge"的推理链 |
| 可审计 | 金额/凯利/敞口等关键计算全部由**确定性内核**完成，不交给 LLM 心算 |
| 可回测 | 数据源、预测、风控解耦，预测概率可被历史赛果回测校准 |
| 可降级 | 无 API Key 时用确定性基线模型端到端跑通；有 Key 时升级为多智能体 |
| 风险可控 | 价值阈值 + 分数凯利 + 单注上限 + 组合敞口上限四道闸 |

**核心理念：LLM 负责"软判断"（读伤停新闻、估概率、解读盘口分歧），
确定性代码负责"硬计算"（去水位、EV、凯利、敞口约束）。** 钱怎么下，永远由可测的代码决定。

## 2. 智能体编排

```
                         ┌─────────────────────────┐
   match_id ───────────► │   协调智能体 Orchestrator │
                         └────────────┬─────────────┘
            ┌──────────────┬──────────┼───────────┬──────────────┐
            ▼              ▼          ▼            ▼              ▼
     数据采集智能体   盘口聚合智能体  赛事分析智能体  价值投注智能体   风控智能体
   DataCollector  OddsAggregator  MatchAnalyst  ValueBetting   RiskManager
        │              │              │            │              │
   get_match      get_odds   baseline_prediction evaluate_value_bets (复核)
        └──────────────┴──────┬───────┴────────────┴──────────────┘
                              ▼
                  确定性风控内核 (risk.py)  ──►  投注推荐 BetRecommendation
```

| 智能体 | 单一职责 | 输入 | 输出 | 工具 |
| --- | --- | --- | --- | --- |
| DataCollector | 采集结构化赛事信息 | match_id | 实力/状态/伤停要点 | `get_match` |
| OddsAggregator | 聚合并比较盘口 | match_id | 体彩 vs Polymarket 对比、抽水、分歧 | `get_odds` |
| MatchAnalyst | 产出校准真实概率 | 上述 + 基线 | `{p_home,p_draw,p_away,confidence}` | `baseline_prediction` |
| ValueBetting | 找正期望机会 | 概率 | 各盘口 edge/凯利 | `evaluate_value_bets` |
| RiskManager | 稳健性复核 + 风险提示 | 价值机会 | 最终推荐口径 | — |
| Orchestrator | 编排与汇总 | match_id | 结构化报告 | 委派子智能体 |

实现见 `src/worldcup_betting/agents/definitions.py`，运行器见 `agents/runner.py`。

## 3. 数据流（统一到十进制赔率）

```
体彩竞彩(十进制赔率) ─┐
                      ├─► MarketOdds(decimal_odds) ─► remove_vig ─► 隐含概率(无抽水)
Polymarket价格(0~1) ──┘   (price→1/price)                              │
                                                                       ▼
赛事数据 ─► MatchAnalyst ─► Prediction(真实概率) ──► find_value_bets ─► ValueAssessment
                                                          (edge=p·d−1)      │
                                                                            ▼
                                                  build_recommendations ─► BetRecommendation
                                                  (置信度闸/凯利/单注&组合上限)
```

- **体彩**：竞彩足球本身是固定十进制赔率，直接落入 `MarketOdds`。
- **Polymarket**：是预测市场，outcome 份额价格 `price∈(0,1)` 即隐含概率，
  通过 `decimal = 1/price` 归一，使两类盘口在同一坐标系下可比。

## 4. 关键数学（`tools/analytics.py`）

| 量 | 公式 |
| --- | --- |
| 隐含概率 | `p = 1/d` |
| 去水位 | `p_i = (1/d_i) / Σ(1/d_j)`（按比例归一化） |
| 抽水 overround | `Σ(1/d_j) − 1` |
| 期望值 / edge | `EV = p·d − 1` |
| 完整凯利 | `f* = (p·d − 1)/(d − 1)` |
| 实际下注比例 | `min(f*·kelly_scale, max_fraction)`，再受组合敞口缩放 |

为何用**分数凯利**：完整凯利对概率估计误差极其敏感，估高一点就可能严重过注。
默认 1/4 凯利 + 5% 单注上限 + 20% 组合上限，是工程上稳健的保守组合。

## 5. 模块结构

```
src/worldcup_betting/
├── models.py            数据模型（Match/MarketOdds/Prediction/ValueAssessment/BetRecommendation）
├── config.py            风控参数与运行开关
├── tools/
│   ├── analytics.py     纯数学内核（赔率/EV/凯利/价值扫描）★ 全单测覆盖
│   ├── baseline_model.py 确定性基线预测器（降级路径 & 对照基准）
│   ├── match_data.py    赛事数据 Provider 接口 + Mock
│   └── odds_providers.py 体彩 / Polymarket Provider 接口 + Mock
├── risk.py              风控内核：价值评估 → 受约束的投注建议
├── orchestrator.py      编排：数据→预测→价值→风控（确定性 & 智能体共用出口）
├── sdk_tools.py         把能力暴露为 Claude Agent SDK 的 in-process MCP 工具
└── agents/
    ├── definitions.py   各智能体 system prompt 与工具授权
    └── runner.py        用 ClaudeSDKClient 驱动多智能体并解析概率
```

## 6. 接真实数据源

各 Provider 已抽象为接口，接实盘只需新增实现、不改上层：

- **体彩**：解析竞彩足球胜平负固定赔率（官方/聚合站）。注意只取公开赔率数据。
- **Polymarket**：经 Gamma / CLOB API 读取对应市场 outcome 价格，
  按 `1/price` 转十进制赔率。注意流动性低时点差大，需在 RiskManager 加流动性过滤。
- **赛事数据**：API-Football / FotMob 等，补充 xG、阵容、主客场细分等特征。

## 7. 路线图（建议增量）

1. **概率模型升级**：基线 → Elo / Dixon-Coles（进球数）/ 集成 xG，并做概率校准（Brier/log-loss）。
2. **回测框架**：用历史赛季 + 历史盘口回测策略的 ROI、最大回撤、命中率。
3. **盘口异动监控**：抓取赔率时间序列，识别热钱流向与错盘（value 来源往往是早盘）。
4. **跨盘口套利/中和**：体彩与 Polymarket 反向时的对冲机会检测。
5. **可观测性**：记录每条建议与最终赛果，闭环评估模型与策略表现。

## 8. 合规与风险声明

- 系统**仅做分析与推荐**，不提供自动下注，不规避任何平台限制。
- 中国大陆仅体彩为合法体育彩票；Polymarket 等在部分法域受限。用户须遵守所在地法律法规。
- 任何模型都无法保证盈利。请理性投注、量力而行，切勿借贷投注。
