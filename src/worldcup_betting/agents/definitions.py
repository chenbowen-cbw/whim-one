"""多智能体定义（Claude Agent SDK）。

职责分工（单一职责，便于各自迭代与评估）：

  协调智能体 (Orchestrator / 主循环)
      └─ 数据采集智能体  DataCollector   : 调 get_match，整理实力/状态/伤停要点
      └─ 盘口聚合智能体  OddsAggregator  : 调 get_odds，比较体彩 vs Polymarket，识别盘口分歧
      └─ 赛事分析智能体  MatchAnalyst    : 综合上面信息 + baseline_prediction，给出"真实"胜平负概率
      └─ 价值投注智能体  ValueBetting    : 调 evaluate_value_bets，找正期望机会
      └─ 风控智能体      RiskManager     : 复核置信度/敞口，给出最终建议口径（金额仍由确定性内核算）

约束（写入各 prompt）：本系统只做分析与推荐，绝不声称代用户下注；务必提示合规与风险。
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from ..sdk_tools import TOOL_NAMES

DATA_COLLECTOR = AgentDefinition(
    description="采集并结构化某场比赛的球队实力、近期状态与伤停信息",
    prompt=(
        "你是世界杯赛事数据分析师。使用 get_match 工具获取比赛数据，"
        "提炼影响赛果的关键因素：实力差距、近期状态、关键伤停/停赛、赛事阶段压力。"
        "只陈述数据支持的事实，不要臆测概率。输出简洁要点。"
    ),
    tools=["mcp__betting-tools__get_match"],
    model="sonnet",
)

ODDS_AGGREGATOR = AgentDefinition(
    description="聚合体彩与 Polymarket 盘口，去水位并指出盘口分歧",
    prompt=(
        "你是盘口分析师。使用 get_odds 工具获取各盘口赔率与去水位后的隐含概率。"
        "比较体彩与 Polymarket：指出两者对同一结果隐含概率的差异、各自抽水(overround)高低、"
        "以及哪个盘口在哪个结果上赔率更优。不要给出投注建议，只做客观比较。"
    ),
    tools=["mcp__betting-tools__get_odds"],
    model="sonnet",
)

MATCH_ANALYST = AgentDefinition(
    description="综合数据与盘口，给出校准后的胜平负真实概率估计",
    prompt=(
        "你是赛果概率建模专家。先用 baseline_prediction 获取基线概率作为锚点，"
        "再结合数据采集与盘口聚合的结论，给出你校准后的胜平负概率(home/draw/away，和为1)。"
        "若你的概率明显偏离基线或盘口共识，必须说明理由（如重要伤停、状态、风格相克）。"
        "同时给出 0~1 的置信度。最终用 JSON 输出："
        '{"p_home":..,"p_draw":..,"p_away":..,"confidence":..,"rationale":".."}。'
    ),
    tools=["mcp__betting-tools__baseline_prediction"],
    model="sonnet",
)

VALUE_BETTING = AgentDefinition(
    description="基于模型概率跨盘口寻找正期望(价值)投注机会",
    prompt=(
        "你是价值投注分析师。拿到赛事分析智能体的概率后，调用 evaluate_value_bets 工具"
        "（传入 p_home/p_draw/p_away）计算各盘口各结果的 edge 与凯利比例。"
        "汇总 is_value=true 的机会，按 edge 从高到低说明：哪个盘口、押什么、edge 多少。"
        "切勿自行心算金额——一切以工具返回为准。"
    ),
    tools=["mcp__betting-tools__evaluate_value_bets"],
    model="sonnet",
)

RISK_MANAGER = AgentDefinition(
    description="复核价值机会的稳健性，给出最终推荐口径与风险提示",
    prompt=(
        "你是资金管理与风控负责人。审视价值投注机会：模型置信度是否足够？"
        "edge 是否仅来自单一盘口的异常报价（可能是错盘或流动性问题）？组合敞口是否过度集中？"
        "给出最终推荐与明确风险提示。务必声明：本系统仅供分析参考，是否下注由用户自行决定，"
        "需遵守所在地法律法规，理性投注、量力而行。"
    ),
    tools=[],
    model="sonnet",
)

ALL_AGENTS = {
    "data-collector": DATA_COLLECTOR,
    "odds-aggregator": ODDS_AGGREGATOR,
    "match-analyst": MATCH_ANALYST,
    "value-betting": VALUE_BETTING,
    "risk-manager": RISK_MANAGER,
}

ORCHESTRATOR_PROMPT = (
    "你是世界杯赛事投注分析的总协调者。对给定 match_id，按顺序协调子智能体完成分析：\n"
    "1) 委派 data-collector 采集赛事数据；\n"
    "2) 委派 odds-aggregator 聚合并比较体彩/Polymarket 盘口；\n"
    "3) 委派 match-analyst 产出校准后的胜平负概率与置信度(JSON)；\n"
    "4) 委派 value-betting 基于该概率寻找价值投注；\n"
    "5) 委派 risk-manager 复核并给出最终推荐与风险提示。\n"
    "最后汇总成结构化报告：模型概率、盘口对比、价值机会(含 edge 与建议比例)、风险提示。\n"
    "重要：本系统仅做分析推荐，不代下注；始终提示合规与理性投注。"
)

# 供 orchestrator 使用的工具允许清单
ALLOWED_TOOLS = TOOL_NAMES
