"""主流程示例：对一场比赛跑完整分析并打印投注推荐报告。

用法：
    python examples/analyze_match.py                      # 确定性路径（无需 API Key）
    ANTHROPIC_API_KEY=sk-... python examples/analyze_match.py --agents   # 启用多智能体

确定性路径用基线模型 + 纯数学，离线即可跑通；--agents 路径用 Claude Agent SDK
多智能体产出概率，再交给同一套风控内核。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from worldcup_betting.config import AppConfig  # noqa: E402
from worldcup_betting.models import Outcome  # noqa: E402
from worldcup_betting.orchestrator import AnalysisResult, analyze_match  # noqa: E402

_OUTCOME_CN = {Outcome.HOME: "主胜", Outcome.DRAW: "平局", Outcome.AWAY: "客胜"}
MATCH_ID = "WC2026-G-ARG-MEX"


def print_report(res: AnalysisResult) -> None:
    m = res.match
    print("=" * 60)
    print(f"赛事分析报告  {m.home.name} vs {m.away.name}  ({m.stage})")
    print(f"开赛: {m.kickoff}  场地: {m.venue}")
    print("=" * 60)

    print("\n[模型预测]  (置信度 {:.0%})".format(res.prediction.confidence))
    for o in Outcome:
        print(f"  {_OUTCOME_CN[o]}: {res.prediction.probabilities[o]:.1%}")
    print(f"  依据: {res.prediction.rationale}")

    print("\n[盘口对比]  (去水位隐含概率)")
    from worldcup_betting.tools.analytics import overround, remove_vig

    for od in res.odds:
        fair = remove_vig(od.decimal_odds)
        line = "  ".join(
            f"{_OUTCOME_CN[o]} {od.decimal_odds[o]:.2f}/{fair[o]:.0%}" for o in Outcome
        )
        print(f"  {od.bookmaker.value:11s} | {line} | 抽水 {overround(od.decimal_odds)-1:+.1%}")

    print("\n[投注推荐]")
    if not res.recommendations:
        print("  本场无满足价值阈值与风控条件的投注机会，建议观望。")
    else:
        for r in res.recommendations:
            print(
                f"  ▶ {r.bookmaker.value} 押 {_OUTCOME_CN[r.outcome]} @ {r.decimal_odds:.2f} | "
                f"EV {r.expected_value:+.1%} | 建议 {r.stake_fraction:.1%} 资金 (≈{r.stake_amount:.0f})"
            )
            print(f"     {r.rationale}")

    print("\n⚠ 免责声明：本系统仅供赛事分析与研究参考，不构成投注建议。")
    print("  是否投注由用户自行决定，请遵守所在地法律法规，理性投注、量力而行。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", action="store_true", help="启用 Claude Agent SDK 多智能体层")
    parser.add_argument("--match", default=MATCH_ID)
    args = parser.parse_args()

    cfg = AppConfig.from_env()

    prediction = None
    if args.agents:
        if not cfg.anthropic_api_key:
            print("未检测到 ANTHROPIC_API_KEY，回退到确定性路径。\n")
        else:
            from worldcup_betting.agents.runner import run_agent_prediction

            prediction, transcript = asyncio.run(run_agent_prediction(args.match))
            print("---- 多智能体对话摘要 ----")
            print(transcript[-1500:])
            print("---- 摘要结束 ----\n")
            if prediction is None:
                print("未能从智能体输出解析出概率，回退到基线模型。\n")

    res = analyze_match(args.match, cfg, prediction=prediction)
    print_report(res)


if __name__ == "__main__":
    main()
