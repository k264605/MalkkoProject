# core/state.py  (디스코드 import 금지)
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

from config import RULES



class Stage(str, Enum):
    NORMAL = "normal"          # 값은 GIF 파일명과 같게
    DENIAL = "denial"
    ANGER = "anger"
    BARGAINING = "bargaining"
    DEPRESSION = "depression"
    ACCEPTANCE = "acceptance"


# (단계, 하한 체력): 위에서부터 검사. 순서 = 나빠지는 순서
STAGE_FLOORS: tuple[tuple[Stage, int], ...] = (
    (Stage.NORMAL, 84),
    (Stage.DENIAL, 67),
    (Stage.ANGER, 50),
    (Stage.BARGAINING, 34),
    (Stage.DEPRESSION, 17),
    (Stage.ACCEPTANCE, 0),
)
STAGE_RANK = {stage: i for i, (stage, _) in enumerate(STAGE_FLOORS)}  # 클수록 나쁨


def stage_of(hp: float) -> Stage:
    """체력 -> 단계. hp는 float도 받는다 (83.9 -> 부정)."""
    for stage, floor in STAGE_FLOORS:
        if hp >= floor:
            return stage
    return Stage.ACCEPTANCE


@dataclass(frozen=True)
class Team:
    start: datetime   # tz-aware UTC
    end: datetime


@dataclass(frozen=True)
class Mascot:
    hp: float
    last_decay_at: datetime
    speed_tier: float = 1.0                  # 1.0 / 1.5 / 2.0 / 마감 후 0.0
    acceptance_since: datetime | None = None
    last_action_at: datetime | None = None
    revive_count: int = 0
    skin_level: int = 1

    @property
    def stage(self) -> Stage:
        return stage_of(self.hp)


@dataclass(frozen=True)
class Change:
    """코어 계산의 결과. 연결부는 after를 저장하고, 프로퍼티로 알림 여부를 판단한다."""
    before: Mascot
    after: Mascot

    @property
    def hp_delta(self) -> float:
        return self.after.hp - self.before.hp

    @property
    def stage_changed(self) -> bool:
        return self.after.stage != self.before.stage

    @property
    def stage_dropped(self) -> bool:
        return STAGE_RANK[self.after.stage] > STAGE_RANK[self.before.stage]

    @property
    def stage_rose(self) -> bool:
        return STAGE_RANK[self.after.stage] < STAGE_RANK[self.before.stage]

    @property
    def entered_acceptance(self) -> bool:
        return self.after.stage is Stage.ACCEPTANCE and self.before.stage is not Stage.ACCEPTANCE

    @property
    def entered_acceleration(self) -> bool:
        return self.after.speed_tier > max(self.before.speed_tier, 1.0)

    @property
    def revived(self) -> bool:
        return self.after.revive_count > self.before.revive_count


def total_hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def hours_to_acceptance(start: datetime, end: datetime) -> float:
    """T: 기간의 10%, 최소 48시간 ~ 최대 168시간."""
    t = total_hours(start, end) * RULES.acceptance_ratio
    return min(max(t, RULES.acceptance_min_hours), RULES.acceptance_max_hours)


def speed_multiplier(start: datetime, end: datetime, now: datetime) -> float:
    """남은 기간 25% 이하 1.5, 10% 이하 2.0, 마감 후 0."""
    total = end - start
    if total <= timedelta(0) or now >= end:
        return 0.0
    remaining_ratio = (end - now) / total
    for ratio, mult in RULES.speed_tiers:        # 작은 비율부터
        if remaining_ratio <= ratio:
            return mult
    return 1.0


def decay(m: Mascot, team: Team, now: datetime) -> Change | None:
    """last_decay_at ~ now 사이의 체력 감소. 배속 구간 경계에서 나눠 계산한다.
    체력도 배속 단계도 안 바뀌면 None."""
    last = max(m.last_decay_at, team.start)      # 시작 전에는 감소 없음
    if now <= last:
        return None

    total = team.end - team.start
    boundaries = {team.end}
    for ratio, _ in RULES.speed_tiers:
        boundaries.add(team.end - total * ratio)
    cuts = sorted(p for p in boundaries if last < p < now)
    edges = [last, *cuts, now]

    base_rate = RULES.hp_decay_span / hours_to_acceptance(team.start, team.end)  # 시간당
    loss = 0.0
    for a, b in zip(edges, edges[1:]):
        hours = (b - a).total_seconds() / 3600
        mid = a + (b - a) / 2        # 경계 반올림 오차를 피하려고 구간 중간으로 판정
        loss += hours * base_rate * speed_multiplier(team.start, team.end, mid)

    new_hp = max(0.0, m.hp - loss)
    tier_now = speed_multiplier(team.start, team.end, now)
    if new_hp == m.hp and tier_now == m.speed_tier:
        return None

    after = replace(m, hp=new_hp, speed_tier=tier_now, last_decay_at=now)
    if stage_of(new_hp) is Stage.ACCEPTANCE and m.stage is not Stage.ACCEPTANCE:
        after = replace(after, acceptance_since=now)
    return Change(before=m, after=after)

