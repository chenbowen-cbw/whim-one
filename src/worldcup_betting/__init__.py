"""世界杯多智能体赛事分析与投注推荐系统（仅分析推荐，不自动下注）。"""

from .config import AppConfig, RiskConfig
from .orchestrator import AnalysisResult, analyze_match

__all__ = ["AppConfig", "RiskConfig", "AnalysisResult", "analyze_match"]
