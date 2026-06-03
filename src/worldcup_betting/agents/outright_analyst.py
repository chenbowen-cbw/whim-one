"""夺冠概率分析智能体：自动产出各队夺冠概率，喂给价值扫描，形成闭环。

两条路径，对外接口一致 (produce_outright_beliefs)：
- LLM 路径（有 ANTHROPIC_API_KEY + claude-agent-sdk）：分析师读真实夺冠盘，结合
  实力/状态/赛制，给出校准后的 {队名: 概率} 与理由。
- 确定性路径（降级）：用热门-冷门偏差修正(favorite_longshot_beliefs)产出基线判断。

无论哪条路径，产出的概率最终都交给同一套确定性价值扫描与风控内核。
"""

from __future__ import annotations

import json
import re

from ..tools.outright_model import favorite_longshot_beliefs

# 分析师 prompt 与工具授权（AgentDefinition 在 LLM 路径内惰性构建，避免顶层依赖 SDK）
_ANALYST_PROMPT = (
    "你是世界杯夺冠概率建模专家。先用 get_outright_market 工具获取真实夺冠盘"
    "（各队市场隐含概率/赔率/流动性）。然后结合你对球队实力、阵容、近期状态、"
    "赛制(签表难度)、历史大赛表现的认知，给出你校准后的夺冠概率。\n"
    "注意：预测市场存在热门-冷门偏差(高估冷门、低估热门)，请审慎判断哪些队被错误定价。\n"
    "只对你最有把握的、流动性充足(>$50k)的球队给出判断(通常 5~12 支)。\n"
    "概率无需对全部球队归一(你只覆盖部分队)，但每支概率应在(0,1)且合理。\n"
    '最终严格用 JSON 输出：{"beliefs": {"France": 0.18, "Argentina": 0.12, ...}, '
    '"rationale": "你为何如此判断"}。'
)


def _extract_beliefs(transcript: str) -> dict[str, float] | None:
    """从智能体输出中解析最后一个含 beliefs 的 JSON。"""
    # 贪婪匹配带 beliefs 的对象（允许嵌套一层）
    for blob in reversed(re.findall(r"\{(?:[^{}]|\{[^{}]*\})*beliefs(?:[^{}]|\{[^{}]*\})*\}", transcript)):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        beliefs = data.get("beliefs")
        if isinstance(beliefs, dict) and beliefs:
            out = {}
            for team, p in beliefs.items():
                try:
                    out[str(team)] = float(p)
                except (TypeError, ValueError):
                    continue
            if out:
                return out
    return None


async def produce_outright_beliefs_llm() -> tuple[dict[str, float] | None, str]:
    """运行 LLM 分析师，返回 (beliefs, 对话文本)。需 SDK + API Key。"""
    from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, ClaudeSDKClient

    from ..sdk_tools import build_mcp_server

    analyst = AgentDefinition(
        description="基于真实夺冠盘与球队基本面，产出各队夺冠的校准概率",
        prompt=_ANALYST_PROMPT,
        tools=["mcp__betting-tools__get_outright_market"],
        model="sonnet",
    )
    options = ClaudeAgentOptions(
        system_prompt="你是严谨的体育博彩量化分析师，只输出有依据的概率判断。",
        mcp_servers={"betting-tools": build_mcp_server()},
        allowed_tools=["mcp__betting-tools__get_outright_market"],
        agents={"outright-analyst": analyst},
        model="sonnet",
    )
    parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            "请委派 outright-analyst 分析世界杯夺冠盘，产出各队夺冠概率的 JSON。"
        )
        async for message in client.receive_response():
            for block in getattr(message, "content", []) or []:
                if getattr(block, "text", None):
                    parts.append(block.text)
    transcript = "\n".join(parts)
    return _extract_beliefs(transcript), transcript


def produce_outright_beliefs(
    rows: list[dict],
    *,
    use_llm: bool,
    gamma: float = 1.12,
    top_n: int = 10,
) -> tuple[dict[str, float], str]:
    """统一入口：返回 (beliefs, 来源说明)。

    use_llm=True 且可用时走 LLM；否则(或解析失败)降级到热门-冷门偏差基线。
    rows 用于降级路径与 top_n 聚焦。
    """
    if use_llm:
        try:
            import asyncio

            beliefs, _ = asyncio.run(produce_outright_beliefs_llm())
            if beliefs:
                return beliefs, "LLM 分析师(outright-analyst)"
        except Exception as e:  # noqa: BLE001 — 任何失败都安全降级
            print(f"[warn] LLM 路径不可用，降级到基线：{e}")
    return (
        favorite_longshot_beliefs(rows, gamma=gamma, top_n=top_n),
        f"确定性基线(热门-冷门偏差修正, gamma={gamma})",
    )
