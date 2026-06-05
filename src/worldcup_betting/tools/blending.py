"""把模型概率向盘口先验收缩（混合），以盘口为锚、只在有把握处偏离。

动机：校准后的模拟仍有系统性偏差(高估弱洲强队、单场方差压平大热门)，直接拿去算 edge
会产出夸张假信号。把模型概率与盘口隐含概率按置信度 λ 混合，可控地保留"模型相对盘口的
观点"，同时不偏离市场太远。

默认用**对数线性池(几何混合)**——它正是"收缩模型相对盘口的偏离"这一操作：
    p_blend(k) ∝ p_market(k)^(1-λ) · p_model(k)^λ        (在两者共同覆盖的队上归一)
等价于  log(p_blend/p_market) = λ·log(p_model/p_market)：模型的对数偏离被缩放 λ 倍。
  λ=0 → 完全等于盘口(零观点、零 edge)；λ=1 → 完全是模型；0<λ<1 → 受控偏离。

线性池(算术混合)作为备选：p_blend = λ·p_model + (1-λ)·p_market。
"""

from __future__ import annotations

import math

_EPS = 1e-9


def blend_beliefs(
    model: dict[str, float],
    market: dict[str, float],
    *,
    weight: float = 0.35,
    method: str = "geometric",
) -> dict[str, float]:
    """在 model 与 market 的共同队集上混合，归一后返回 {队: 概率}。

    weight(λ): 对模型的信任度(0~1)。0=纯盘口，1=纯模型。
    method: "geometric"(对数线性池，默认) 或 "linear"(算术池)。
    队名匹配要求两侧 key 规范一致(建议都用 dataset_name 规范化)。
    """
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"weight 需在 [0,1]，得到 {weight}")
    keys = [k for k in model if k in market]
    if not keys:
        return {}

    if method == "geometric":
        raw = {
            k: math.exp(weight * math.log(max(model[k], _EPS))
                        + (1 - weight) * math.log(max(market[k], _EPS)))
            for k in keys
        }
    elif method == "linear":
        raw = {k: weight * model[k] + (1 - weight) * market[k] for k in keys}
    else:
        raise ValueError(f"未知 method: {method}")

    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}


def blend_independent(
    model: dict[str, float],
    market: dict[str, float],
    *,
    weight: float = 0.35,
) -> dict[str, float]:
    """独立(非互斥)事件的收缩，用 logit(对数几率)线性混合，逐队独立、不跨队归一。

    适用于"进16强/8强/4强"这类各队各自成立的 Yes/No 盘口（概率之和不为1）：
        logit(p_blend) = λ·logit(p_model) + (1-λ)·logit(p_market)
    λ=0 纯盘口，λ=1 纯模型。
    """
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"weight 需在 [0,1]，得到 {weight}")

    def _logit(p: float) -> float:
        p = min(max(p, _EPS), 1.0 - _EPS)
        return math.log(p / (1.0 - p))

    out: dict[str, float] = {}
    for k in model:
        if k in market:
            z = weight * _logit(model[k]) + (1 - weight) * _logit(market[k])
            out[k] = 1.0 / (1.0 + math.exp(-z))
    return out
