# core/policy.py  (디스코드 import 금지)
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from core.classify import Classification
from core.state import STAGE_RANK, Stage

NAG_FROM_STAGE = Stage.ANGER            # 분노 이하일 때만
NAG_COOLDOWN = timedelta(hours=1)       # 팀 기준 1시간에 한 번


class BotAction(str, Enum):
    NONE = "none"
    NAG = "nag"                         # 잔소리
    # OFFER_BUTTON은 B 단계에서 추가


def decide(
    result: Classification, stage: Stage, last_nag_at: datetime | None, now: datetime,
) -> BotAction:
    if not result.is_chitchat:
        return BotAction.NONE
    if STAGE_RANK[stage] < STAGE_RANK[NAG_FROM_STAGE]:
        return BotAction.NONE
    if last_nag_at is not None and now - last_nag_at < NAG_COOLDOWN:
        return BotAction.NONE
    return BotAction.NAG