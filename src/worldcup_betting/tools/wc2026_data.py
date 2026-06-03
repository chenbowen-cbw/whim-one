"""2026 世界杯赛制数据：48 队、12 组、每组 4 队。

⚠ power 评分与分组为**示意值**（基于大致实力档次），仅用于演示模拟器机制。
真实使用前应：
  - 用 Elo / 历史比分最大似然拟合 power；
  - 用官方抽签结果替换分组。
power 取 0~100 的"实力分"，越高越强，喂给进球模型。
"""

from __future__ import annotations

# {组: [(队名, power), ...]}，每组 4 队
GROUPS: dict[str, list[tuple[str, float]]] = {
    "A": [("Mexico", 74), ("Norway", 72), ("Ivory Coast", 64), ("New Zealand", 48)],
    "B": [("Canada", 70), ("Ecuador", 71), ("Egypt", 66), ("Uzbekistan", 55)],
    "C": [("USA", 73), ("Colombia", 80), ("Tunisia", 60), ("Qatar", 52)],
    "D": [("Spain", 92), ("Croatia", 79), ("Japan", 72), ("Ghana", 60)],
    "E": [("France", 93), ("Switzerland", 74), ("Senegal", 73), ("Jordan", 50)],
    "F": [("Argentina", 90), ("Austria", 71), ("South Korea", 70), ("Panama", 49)],
    "G": [("England", 89), ("Uruguay", 78), ("Iran", 64), ("Saudi Arabia", 54)],
    "H": [("Brazil", 89), ("Denmark", 75), ("Mexico B", 60), ("Curacao", 45)],
    "I": [("Portugal", 88), ("Morocco", 76), ("Australia", 66), ("Haiti", 46)],
    "J": [("Netherlands", 85), ("Nigeria", 71), ("Scotland", 65), ("Cape Verde", 52)],
    "K": [("Germany", 86), ("Belgium", 82), ("Paraguay", 63), ("Jamaica", 53)],
    "L": [("Italy", 83), ("Algeria", 67), ("Peru", 62), ("Honduras", 50)],
}


def default_ratings() -> dict[str, float]:
    return {name: power for teams in GROUPS.values() for name, power in teams}
