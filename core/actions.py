# core/actions.py  (디스코드 import 금지)
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from enum import Enum

from config import RULES
from core.state import Change, Mascot, Stage


class ActionKind(str, Enum):
    PROGRESS = "progress"            # /진행
    STUCK_REQUEST = "stuck_request"  # /막힘 요청
    STUCK_HELP = "stuck_help"        # 도와줄게 버튼
    VOTE = "vote"                    # 회의 투표 참여 (1명당)
    VOTE_ALL = "vote_all"            # 투표 전원 참여 보너스


HEAL: dict[ActionKind, int] = {
    ActionKind.PROGRESS: 15,
    ActionKind.STUCK_REQUEST: 5,
    ActionKind.STUCK_HELP: 20,
    ActionKind.VOTE: 10,
    ActionKind.VOTE_ALL: 20,
}

# 1인당 쿨다운. 없는 종류는 제한 없음.
COOLDOWNS: dict[ActionKind, timedelta] = {
    ActionKind.PROGRESS: timedelta(hours=6),
    ActionKind.STUCK_REQUEST: timedelta(hours=1),
    ActionKind.VOTE: timedelta(hours=1),            # ← 추가: 투표를 계속 만들어 보상 받는 것 방지
}


def cooldown_remaining(kind: ActionKind, last_at: datetime | None, now: datetime) -> timedelta:
    """이 사용자가 같은 종류를 마지막으로 한 시각(last_at) 기준 남은 대기 시간. 0이면 가능."""
    cd = COOLDOWNS.get(kind)
    if cd is None or last_at is None:
        return timedelta(0)
    return max(timedelta(0), last_at + cd - now)


def is_allowed(m: Mascot, kind: ActionKind) -> bool:
    """수용 단계에서는 부활 미션(진행)만 열린다."""
    if m.stage is Stage.ACCEPTANCE:
        return kind is ActionKind.PROGRESS
    return True


def revive_required(member_count: int) -> int:
    """부활에 필요한 인원: 과반 (2명이면 2, 3명이면 2, 4명이면 3)."""
    return max(1, member_count // 2 + 1)


def apply_action(
    m: Mascot,
    kind: ActionKind,
    now: datetime,
    *,
    actor_id: int | None = None,
    sharers: frozenset[int] = frozenset(),
    member_count: int = 1,
) -> Change | None:
    """협업 행동을 반영한다.

    - 수용 단계: 진행만 인정. 수용 진입 후 진행을 공유한 사람(sharers + 지금 행동한 사람)이
      과반이면 부활(체력 100, 외형 lv2), 아니면 None.
    - 그 외 단계: 행동별 회복량만큼 회복 (최대 100). 이미 100이어도 last_action_at은 갱신.
    - 허용되지 않은 행동이거나 회복량이 없으면 None.

    sharers에 actor_id가 이미 들어 있어도 합집합이라 중복 집계되지 않는다.
    """
    if not is_allowed(m, kind):
        return None

    if m.stage is Stage.ACCEPTANCE:
        if actor_id is None:
            raise ValueError("수용 단계에서는 actor_id가 필요합니다.")
        if len(set(sharers) | {actor_id}) < revive_required(member_count):
            return None
        after = replace(
            m,
            hp=float(RULES.hp_max),
            last_action_at=now,
            last_decay_at=now,
            acceptance_since=None,
            revive_count=m.revive_count + 1,
            skin_level=max(m.skin_level, 2),
        )
        return Change(before=m, after=after)

    heal = HEAL.get(kind, 0)
    if heal <= 0:
        return None
    after = replace(m, hp=min(float(RULES.hp_max), m.hp + heal), last_action_at=now)
    return Change(before=m, after=after)


def motion_for(change: Change, *, everyone: bool = False) -> str:
    """보낼 모션: 부활·전원 참여 shine, 단계 상승 healthy, 그 외 happy."""
    if change.revived or everyone:
        return "shine"
    if change.stage_rose:
        return "healthy"
    return "happy"