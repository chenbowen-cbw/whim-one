"""把内部能力暴露为 Claude Agent SDK 的 in-process MCP 工具。

智能体通过这些工具读取数据、执行精确计算。注意：**金额/凯利等关键计算一律走工具**
（即确定性内核），不让模型自由心算，确保可审计、不被幻觉影响。

仅在安装了 claude-agent-sdk 且配置 API Key 时才需要本模块。
"""

from __future__ import annotations

import json

from claude_agent_sdk import create_sdk_mcp_server, tool

from .models import Bookmaker, MarketOdds, Outcome, Prediction
from .tools.analytics import find_value_bets, overround, remove_vig
from .tools.baseline_model import baseline_predict
from .tools.match_data import MockMatchDataProvider
from .tools.odds_providers import all_mock_providers

# 这些 provider 可在接真实数据源时替换为实盘实现
_MATCH_PROVIDER = MockMatchDataProvider()
_ODDS_PROVIDERS = all_mock_providers()


def _text(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]}


@tool("get_match", "获取一场比赛的基础数据（双方排名、近期状态、伤停）", {"match_id": str})
async def get_match(args: dict) -> dict:
    m = _MATCH_PROVIDER.get_match(args["match_id"])
    return _text(
        {
            "match_id": m.match_id,
            "stage": m.stage,
            "kickoff": m.kickoff.isoformat(),
            "home": {"name": m.home.name, "fifa_rank": m.home.fifa_rank,
                     "form": m.home.recent_form, "injuries": m.home.key_injuries},
            "away": {"name": m.away.name, "fifa_rank": m.away.fifa_rank,
                     "form": m.away.recent_form, "injuries": m.away.key_injuries},
            "notes": m.notes,
        }
    )


@tool("get_odds", "获取所有盘口（体彩、Polymarket）的胜平负赔率及去水位隐含概率", {"match_id": str})
async def get_odds(args: dict) -> dict:
    out = []
    for p in _ODDS_PROVIDERS:
        o = p.get_odds(args["match_id"])
        fair = remove_vig(o.decimal_odds)
        out.append(
            {
                "bookmaker": o.bookmaker.value,
                "decimal_odds": {k.value: v for k, v in o.decimal_odds.items()},
                "implied_prob_no_vig": {k.value: round(v, 4) for k, v in fair.items()},
                "overround": round(overround(o.decimal_odds), 4),
            }
        )
    return _text({"match_id": args["match_id"], "markets": out})


@tool("baseline_prediction", "获取确定性基线模型的胜平负概率，作为对照基准", {"match_id": str})
async def baseline_prediction(args: dict) -> dict:
    m = _MATCH_PROVIDER.get_match(args["match_id"])
    pred = baseline_predict(m)
    return _text(
        {
            "probabilities": {k.value: round(v, 4) for k, v in pred.probabilities.items()},
            "confidence": pred.confidence,
            "rationale": pred.rationale,
        }
    )


@tool(
    "evaluate_value_bets",
    "给定模型概率(home/draw/away，和为1)，跨所有盘口计算 edge / 凯利 / 价值投注",
    {"match_id": str, "p_home": float, "p_draw": float, "p_away": float},
)
async def evaluate_value_bets(args: dict) -> dict:
    pred = Prediction(
        match_id=args["match_id"],
        probabilities={
            Outcome.HOME: args["p_home"],
            Outcome.DRAW: args["p_draw"],
            Outcome.AWAY: args["p_away"],
        },
    )
    odds_list: list[MarketOdds] = [p.get_odds(args["match_id"]) for p in _ODDS_PROVIDERS]
    results = find_value_bets(pred, odds_list)
    return _text(
        {
            "assessments": [
                {
                    "bookmaker": a.bookmaker.value,
                    "outcome": a.outcome.value,
                    "decimal_odds": a.decimal_odds,
                    "model_prob": round(a.model_prob, 4),
                    "implied_prob": round(a.implied_prob, 4),
                    "edge": round(a.edge, 4),
                    "kelly_fraction": round(a.kelly_fraction, 4),
                    "is_value": a.is_value,
                }
                for a in results
            ]
        }
    )


def build_mcp_server():
    """创建供 ClaudeAgentOptions 使用的 in-process MCP server。"""
    return create_sdk_mcp_server(
        name="betting-tools",
        version="1.0.0",
        tools=[get_match, get_odds, baseline_prediction, evaluate_value_bets],
    )


# 供 allowed_tools 引用的完整工具名
TOOL_NAMES = [
    "mcp__betting-tools__get_match",
    "mcp__betting-tools__get_odds",
    "mcp__betting-tools__baseline_prediction",
    "mcp__betting-tools__evaluate_value_bets",
]
