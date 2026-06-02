"""智能体运行器：用 Claude Agent SDK 驱动多智能体协作。

流程：构建 in-process MCP 工具服务 + 子智能体定义 -> 让协调者跑完分析 ->
从对话中解析出 match-analyst 产出的概率 JSON -> 包装成 Prediction，
最终仍交给确定性风控内核(orchestrator.analyze_match)产出金额建议。

仅在安装 claude-agent-sdk 且配置 ANTHROPIC_API_KEY 时可用。
"""

from __future__ import annotations

import json
import re

from ..models import Outcome, Prediction


def _extract_prediction(match_id: str, transcript: str) -> Prediction | None:
    """从智能体输出文本中解析最后一个包含 p_home/p_draw/p_away 的 JSON。"""
    candidates = re.findall(r"\{[^{}]*p_home[^{}]*\}", transcript)
    for blob in reversed(candidates):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if {"p_home", "p_draw", "p_away"} <= data.keys():
            return Prediction(
                match_id=match_id,
                probabilities={
                    Outcome.HOME: float(data["p_home"]),
                    Outcome.DRAW: float(data["p_draw"]),
                    Outcome.AWAY: float(data["p_away"]),
                },
                confidence=float(data.get("confidence", 0.5)),
                rationale=str(data.get("rationale", "")),
            )
    return None


async def run_agent_prediction(match_id: str) -> tuple[Prediction | None, str]:
    """运行多智能体分析，返回 (解析出的Prediction, 完整对话文本)。

    导入放在函数内，避免未安装 SDK 时影响确定性路径。
    """
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    from .definitions import ALL_AGENTS, ALLOWED_TOOLS, ORCHESTRATOR_PROMPT
    from ..sdk_tools import build_mcp_server

    options = ClaudeAgentOptions(
        system_prompt=ORCHESTRATOR_PROMPT,
        mcp_servers={"betting-tools": build_mcp_server()},
        allowed_tools=ALLOWED_TOOLS,
        agents=ALL_AGENTS,
        model="sonnet",
    )

    transcript_parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            f"请对 match_id={match_id} 完成完整的世界杯赛事投注分析，"
            f"务必让 match-analyst 以 JSON 给出胜平负概率与置信度。"
        )
        async for message in client.receive_response():
            for block in getattr(message, "content", []) or []:
                text = getattr(block, "text", None)
                if text:
                    transcript_parts.append(text)

    transcript = "\n".join(transcript_parts)
    return _extract_prediction(match_id, transcript), transcript
