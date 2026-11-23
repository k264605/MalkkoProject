from datetime import datetime, timedelta, timezone

import pytest

from config import RULES
from core.state import (
    STAGE_FLOORS, Mascot, Stage, Team, decay, hours_to_acceptance, speed_multiplier, stage_of,
)

UTC = timezone.utc
START = datetime(2026, 11, 1, tzinfo=UTC)
END = START + timedelta(days=28)          # 4주 -> T = 67.2h, 시간당 1.25
TEAM = Team(START, END)


@pytest.mark.parametrize("hp, stage", [
    (100, Stage.NORMAL), (84, Stage.NORMAL), (83.9, Stage.DENIAL), (67, Stage.DENIAL),
    (66.9, Stage.ANGER), (50, Stage.ANGER), (49.9, Stage.BARGAINING), (34, Stage.BARGAINING),
    (33.9, Stage.DEPRESSION), (17, Stage.DEPRESSION), (16.9, Stage.ACCEPTANCE), (0, Stage.ACCEPTANCE),
])
def test_stage_of(hp, stage):
    assert stage_of(hp) is stage


def test_hours_to_acceptance():
    assert hours_to_acceptance(START, END) == pytest.approx(67.2)                      # 4주
    assert hours_to_acceptance(START, START + timedelta(days=7)) == 48                 # 최소
    assert hours_to_acceptance(START, START + timedelta(weeks=16)) == 168              # 최대


def test_speed_multiplier():
    assert speed_multiplier(START, END, START) == 1.0
    assert speed_multiplier(START, END, END - timedelta(days=8)) == 1.0    # 남은 28.6%
    assert speed_multiplier(START, END, END - timedelta(days=5)) == 1.5    # 17.9%
    assert speed_multiplier(START, END, END - timedelta(days=2)) == 2.0    # 7.1%
    assert speed_multiplier(START, END, END) == 0.0
    assert speed_multiplier(START, END, END + timedelta(hours=1)) == 0.0


def test_decay_one_hour_normal_speed():
    m = Mascot(hp=100, last_decay_at=START)
    c = decay(m, TEAM, START + timedelta(hours=1))
    assert c.after.hp == pytest.approx(98.75)


def test_decay_splits_at_25_percent_boundary():
    b = END - timedelta(days=7)                        # 남은 25% 지점
    m = Mascot(hp=100, last_decay_at=b - timedelta(hours=1))
    c = decay(m, TEAM, b + timedelta(hours=1))
    assert c.after.hp == pytest.approx(100 - 1.25 * (1.0 + 1.5))   # 1시간은 1배, 1시간은 1.5배
    assert c.entered_acceleration
    assert c.after.speed_tier == 1.5


def test_decay_stops_at_deadline():
    m = Mascot(hp=50, last_decay_at=END - timedelta(hours=1), speed_tier=2.0)
    c = decay(m, TEAM, END + timedelta(hours=10))
    assert c.after.hp == pytest.approx(50 - 1.25 * 2.0)            # 마감 전 1시간만 2배
    assert c.after.speed_tier == 0.0


def test_decay_after_deadline_returns_none():
    m = Mascot(hp=50, last_decay_at=END, speed_tier=0.0)
    assert decay(m, TEAM, END + timedelta(hours=10)) is None


def test_decay_enters_acceptance():
    m = Mascot(hp=17.5, last_decay_at=START)
    now = START + timedelta(hours=1)
    c = decay(m, TEAM, now)
    assert c.entered_acceptance and c.stage_changed and c.stage_dropped
    assert c.after.acceptance_since == now


def test_decay_hp_floor_is_zero():
    m = Mascot(hp=1, last_decay_at=START)
    assert decay(m, TEAM, START + timedelta(hours=10)).after.hp == 0


def test_decay_no_time_passed():
    m = Mascot(hp=100, last_decay_at=START + timedelta(hours=1))
    assert decay(m, TEAM, START + timedelta(hours=1)) is None


def test_stage_floors_come_from_rules():
    # 단계 기준값은 config.RULES.stage_floors 한 곳에서만 정한다
    assert tuple((s.value, f) for s, f in STAGE_FLOORS) == RULES.stage_floors
    assert [s for s, _ in STAGE_FLOORS] == list(Stage)       # 모든 단계가 나빠지는 순서로
    for stage, floor in STAGE_FLOORS:
        assert stage_of(floor) is stage
