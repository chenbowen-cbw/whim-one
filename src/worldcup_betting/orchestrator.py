"""编排层：把各"智能体职责"串成一条赛事分析流水线。

提供两种执行路径，对外接口一致（analyze_match）：
- 确定性路径（默认 / 无 API Key）：用基线模型 + 纯数学，端到端可跑、可测、可复现。
- 智能体路径（有 API Key）：由 Claude Agent SDK 多智能体协作产出概率，再交给同一套
  确定性风控内核。详见 agents/ 与 agent_runner.py。

设计原则：LLM 只产出"软判断"（概率/解读），所有"硬计算"（去水位、EV、凯利、敞口）
都由确定性内核执行，保证可审计、可回测、不被幻觉左右下注金额。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .models import BetRecommendation, Match, MarketOdds, Prediction, ValueAssessment
from .risk import build_recommendations
from .tools.analytics import find_value_bets
from .tools.baseline_model import baseline_predict
from .tools.match_data import MatchDataProvider, MockMatchDataProvider
from .tools.odds_providers import OddsProvider, all_mock_providers


@dataclass
class AnalysisResult:
    match: Match
    odds: list[MarketOdds]
    prediction: Prediction
    assessments: list[ValueAssessment]
    recommendations: list[BetRecommendation]


def analyze_match(
    match_id: str,
    cfg: AppConfig,
    *,
    match_provider: MatchDataProvider | None = None,
    odds_providers: list[OddsProvider] | None = None,
    prediction: Prediction | None = None,
) -> AnalysisResult:
    """对单场比赛执行完整分析流水线。

    1. 数据采集：赛事 + 各盘口
    2. 赛果预测：传入的 prediction（如智能体产出）优先，否则用基线模型
    3. 价值评估：跨盘口扫描 edge
    4. 风控：产出受约束的投注建议
    """
    match_provider = match_provider or MockMatchDataProvider()
    odds_providers = odds_providers or all_mock_providers()

    match = match_provider.get_match(match_id)
    odds = [p.get_odds(match_id) for p in odds_providers]

    pred = prediction or baseline_predict(match)

    assessments = find_value_bets(
        pred,
        odds,
        edge_threshold=cfg.risk.edge_threshold,
        kelly_scale=cfg.risk.kelly_scale,
        max_fraction=cfg.risk.max_fraction_per_bet,
    )
    recs = build_recommendations(pred, assessments, cfg.risk)

    return AnalysisResult(
        match=match,
        odds=odds,
        prediction=pred,
        assessments=assessments,
        recommendations=recs,
    )
