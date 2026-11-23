from datetime import datetime, timedelta, timezone

import pytest

from core.actions import (
    ActionKind, apply_action, cooldown_remaining, is_allowed, motion_for, revive_required,
)
from core.state import Mascot, Stage, Team, decay

UTC = timezone.utc
NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
K = ActionKind


def mascot(hp, **kw):
    return Mascot(hp=hp, last_decay_at=NOW, **kw)


@pytest.mark.parametrize("kind, heal", [
    (K.PROGRESS, 15), (K.STUCK_REQUEST, 5), (K.STUCK_HELP, 20), (K.VOTE, 10), (K.VOTE_ALL, 20),
])
def test_heal_amounts(kind, heal):
    c = apply_action(mascot(40), kind, NOW, actor_id=1)
    assert c.hp_delta == heal
    assert c.after.last_action_at == NOW


def test_heal_is_capped_at_100():
    c = apply_action(mascot(95), K.PROGRESS, NOW, actor_id=1)
    assert c.after.hp == 100


def test_already_full_still_records_action():
    c = apply_action(mascot(100), K.PROGRESS, NOW, actor_id=1)
    assert c.hp_delta == 0 and c.after.last_action_at == NOW


def test_motion_happy_when_stage_same():
    c = apply_action(mascot(70), K.STUCK_REQUEST, NOW)        # 70 -> 75, 둘 다 부정
    assert not c.stage_changed
    assert motion_for(c) == "happy"


def test_motion_healthy_when_stage_rises():
    c = apply_action(mascot(55), K.PROGRESS, NOW, actor_id=1)  # 분노 -> 부정
    assert c.stage_rose
    assert motion_for(c) == "healthy"


def test_motion_shine_for_everyone_bonus():
    c = apply_action(mascot(40), K.VOTE_ALL, NOW)
    assert motion_for(c, everyone=True) == "shine"


# ── 수용 단계 / 부활 ─────────────────────────────────
def acceptance(**kw):
    return mascot(10, acceptance_since=NOW - timedelta(hours=1), **kw)


def test_acceptance_blocks_non_progress():
    m = acceptance()
    assert m.stage is Stage.ACCEPTANCE
    assert not is_allowed(m, K.STUCK_HELP)
    assert apply_action(m, K.STUCK_HELP, NOW, actor_id=1) is None


@pytest.mark.parametrize("members, need", [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3)])
def test_revive_required(members, need):
    assert revive_required(members) == need


def test_acceptance_progress_below_majority_returns_none():
    assert apply_action(acceptance(), K.PROGRESS, NOW, actor_id=1, member_count=3) is None


def test_same_person_counted_once():
    c = apply_action(acceptance(), K.PROGRESS, NOW, actor_id=1,
                     sharers=frozenset({1}), member_count=3)
    assert c is None


def test_revive_at_majority():
    c = apply_action(acceptance(), K.PROGRESS, NOW, actor_id=2,
                     sharers=frozenset({1}), member_count=3)
    assert c.revived
    assert c.after.hp == 100 and c.after.stage is Stage.NORMAL
    assert c.after.revive_count == 1 and c.after.skin_level == 2
    assert c.after.acceptance_since is None
    assert motion_for(c) == "shine"


def test_revive_resets_last_decay_at():
    # 체력 0이 된 뒤로는 decay()가 None이라 last_decay_at이 5시간 전에 멈춰 있다
    m = Mascot(hp=0, last_decay_at=NOW - timedelta(hours=5),
               acceptance_since=NOW - timedelta(hours=19))
    c = apply_action(m, K.PROGRESS, NOW, actor_id=2,
                     sharers=frozenset({1}), member_count=3)
    assert c.revived and c.after.last_decay_at == NOW

    team = Team(NOW - timedelta(days=14), NOW + timedelta(days=14))   # 4주 -> 시간당 1.25, 1배속
    d = decay(c.after, team, NOW + timedelta(minutes=1))
    assert d.after.hp == pytest.approx(100 - 1.25 / 60)               # 1분치만 감소 (5시간치 아님)


def test_acceptance_requires_actor_id():
    with pytest.raises(ValueError):
        apply_action(acceptance(), K.PROGRESS, NOW, member_count=3)


# ── 쿨다운 ───────────────────────────────────────────
def test_progress_cooldown():
    assert cooldown_remaining(K.PROGRESS, NOW - timedelta(hours=5), NOW) == timedelta(hours=1)
    assert cooldown_remaining(K.PROGRESS, NOW - timedelta(hours=6), NOW) == timedelta(0)
    assert cooldown_remaining(K.PROGRESS, None, NOW) == timedelta(0)
    assert cooldown_remaining(K.STUCK_HELP, NOW, NOW) == timedelta(0)   # 쿨다운 없는 종류