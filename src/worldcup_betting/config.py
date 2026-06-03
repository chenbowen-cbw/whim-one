"""全局配置。集中管理风控参数与运行开关。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RiskConfig:
    """资金管理与风控参数（所有"硬约束"集中于此，便于审计与回测调参）。"""

    bankroll: float = 10_000.0      # 总资金
    edge_threshold: float = 0.03    # 价值阈值：edge 需 > 3% 才考虑
    kelly_scale: float = 0.25       # 分数凯利系数（1/4 凯利）
    max_fraction_per_bet: float = 0.05   # 单注资金占比上限 5%
    max_total_exposure: float = 0.20     # 单场全部建议合计占比上限 20%
    min_confidence: float = 0.40    # 模型置信度低于此值则不出建议
    min_liquidity: float = 50_000.0  # 盘口流动性($)下限，过低则不出建议（防滑点/错盘）
    min_market_prob: float = 0.0     # 盘口隐含概率下限：过低的极端冷门不碰（模型在此不可信、且有冷门溢价）


@dataclass
class AppConfig:
    risk: RiskConfig
    use_llm_agents: bool            # 是否启用 Claude Agent SDK 智能体层
    anthropic_api_key: str | None

    @classmethod
    def from_env(cls) -> "AppConfig":
        key = os.environ.get("ANTHROPIC_API_KEY")
        return cls(
            risk=RiskConfig(),
            use_llm_agents=bool(key),
            anthropic_api_key=key,
        )
