"""夺冠概率的确定性分析器（降级路径 & LLM 对照基准）。

作用：
1. 无 API Key 时，让"自动产出概率 → 价值扫描"闭环仍能端到端跑通。
2. 作为 LLM 分析智能体的对照基准——智能体的概率若偏离基线，应给出理由。

方法：**热门-冷门偏差(favorite-longshot bias)修正**。
博彩/预测市场存在系统性偏差：散户高估冷门、低估热门，导致冷门赔率偏短(隐含概率偏高)、
热门赔率偏长(隐含概率偏低)。用幂变换对去抽水后的市场概率做校正：

    p_true_i ∝ p_market_i ** gamma     (gamma > 1)

gamma>1 会相对抬高大概率(热门)、压低小概率(冷门)，再归一化。
这刻意保持简单透明；真实场景应叠加实力模型(Elo/夺冠模拟)与定性信息。
"""

from __future__ import annotations


def favorite_longshot_beliefs(
    rows: list[dict],
    *,
    gamma: float = 1.12,
    top_n: int | None = None,
) -> dict[str, float]:
    """对市场去抽水概率做热门-冷门偏差修正，产出 {队名: 概率}。

    rows: event_to_outright_probs() 的输出（需含 team / fair_prob）。
    gamma: 修正强度，>1 抬热门压冷门。1.0 即等于市场（无观点）。
    top_n: 只对市场概率最高的前 N 支返回判断（聚焦流动性好的热门）。
    """
    if not rows:
        return {}
    powered = [(str(r["team"]), max(r["fair_prob"], 1e-9) ** gamma) for r in rows]
    total = sum(p for _, p in powered)
    beliefs = {team: p / total for team, p in powered}

    ranked = sorted(beliefs.items(), key=lambda kv: -kv[1])
    if top_n is not None:
        ranked = ranked[:top_n]
    return dict(ranked)
