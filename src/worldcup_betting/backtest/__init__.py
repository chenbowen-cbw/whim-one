"""回测：在历史/模拟赛事上验证下注策略的 ROI 与风险。"""

from .engine import BacktestMetrics, MarketSnapshot, run_backtest

__all__ = ["BacktestMetrics", "MarketSnapshot", "run_backtest"]
