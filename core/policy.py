# core/policy.py  (디스코드 import 금지)
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from core.classify import Classification
from core.state import STAGE_RANK, Stage

NAG_FROM_STAGE = Stage.ANGER            # 분노 이하일 때만
NAG_COOLDOWN = timedelta(hours=1)       # 팀 기준 1시간에 한 번
NAG_STREAK = 3                          # 잡담만 이 횟수 이상 연속되면 잔소리
STREAK_WINDOW = timedelta(minutes=10)   # 이 시간 안에 이어진 잡담만 '연속'으로 센다


class BotAction(str, Enum):
    NONE = "none"
    NAG = "nag"                         # 잔소리
    # OFFER_BUTTON은 B 단계에서 추가


@dataclass(frozen=True)
class Streak:
    """잡담만 연속된 횟수와 마지막 잡담 시각."""
    count: int = 0
    last_at: datetime | None = None


def update_streak(streak: Streak, is_chitchat: bool, at: datetime) -> Streak:
    """메시지 하나가 들어올 때마다 호출한다.
    잡담이 아니면 0으로 초기화, 잡담이면 시간 간격에 따라 이어 세거나 새로 센다."""
    if not is_chitchat:
        return Streak()
    if streak.last_at is not None and at - streak.last_at <= STREAK_WINDOW:
        return Streak(streak.count + 1, at)
    return Streak(1, at)


def decide(
    result: Classification, stage: Stage, last_nag_at: datetime | None, now: datetime,
    chitchat_streak: int = NAG_STREAK,
) -> BotAction:
    if not result.is_chitchat:
        return BotAction.NONE
    if STAGE_RANK[stage] < STAGE_RANK[NAG_FROM_STAGE]:
        return BotAction.NONE
    if chitchat_streak < NAG_STREAK:
        return BotAction.NONE
    if last_nag_at is not None and now - last_nag_at < NAG_COOLDOWN:
        return BotAction.NONE
    return BotAction.NAG