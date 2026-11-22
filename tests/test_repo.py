import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from config import BASE_DIR
from core.state import Mascot
from db import repo

UTC = timezone.utc
T0 = datetime(2026, 11, 10, tzinfo=UTC)
SCHEMA = BASE_DIR / "db" / "schema.sql"


def run_db(body):
    async def main():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(SCHEMA.read_text(encoding="utf-8"))
        try:
            return await body(db)
        finally:
            await db.close()
    return asyncio.run(main())


async def make_team(db, channel_id=10):
    return await repo.create_team(
        db, guild_id=1, channel_id=channel_id, name="말꼬",
        start=T0, end=T0 + timedelta(days=28), created_at=T0)


def test_create_team_makes_mascot():
    async def body(db):
        team = await make_team(db)
        return team, await repo.get_mascot(db, team.id)
    team, m = run_db(body)
    assert team.end == T0 + timedelta(days=28)
    assert team.to_core().start == T0
    assert m.hp == 100 and m.last_decay_at == T0 and m.skin_level == 1


def test_one_team_per_channel():
    async def body(db):
        await make_team(db)
        with pytest.raises(sqlite3.IntegrityError):
            await make_team(db)
        return await repo.list_teams(db)
    assert len(run_db(body)) == 1


def test_save_mascot_roundtrip():
    m = Mascot(hp=83.25, last_decay_at=T0 + timedelta(hours=3), speed_tier=1.5,
               acceptance_since=T0, last_action_at=T0 + timedelta(hours=1),
               revive_count=1, skin_level=2)
    async def body(db):
        team = await make_team(db)
        await repo.save_mascot(db, team.id, m)
        return await repo.get_mascot(db, team.id)
    assert run_db(body) == m


def test_members():
    async def body(db):
        team = await make_team(db)
        await repo.ensure_member(db, team.id, 1, "가", T0)
        await repo.ensure_member(db, team.id, 1, "가2", T0)
        await repo.ensure_member(db, team.id, 2, "나", T0)
        return await repo.count_members(db, team.id)
    assert run_db(body) == 2


def test_actions_cooldown_and_sharers():
    async def body(db):
        team = await make_team(db)
        await repo.add_action(db, team.id, 1, "progress", 15, T0)
        await repo.add_action(db, team.id, 2, "progress", 15, T0 + timedelta(hours=1))
        last1 = await repo.last_action_at(db, team.id, 1, "progress")
        none3 = await repo.last_action_at(db, team.id, 3, "progress")
        recent = await repo.sharers_since(db, team.id, T0 + timedelta(minutes=30))
        everyone = await repo.sharers_since(db, team.id, T0)
        return last1, none3, recent, everyone
    last1, none3, recent, everyone = run_db(body)
    assert last1 == T0 and none3 is None
    assert recent == frozenset({2}) and everyone == frozenset({1, 2})


def test_reset_demo_restores_everything():
    async def body(db):
        team = await make_team(db)
        await repo.update_team_demo(
            db, team.id, start=T0 - timedelta(days=26), end=T0 + timedelta(days=2),
            demo_offset_hours=500)
        await repo.save_mascot(db, team.id, Mascot(
            hp=10, last_decay_at=T0, skin_level=2, revive_count=1, acceptance_since=T0))
        await repo.add_action(db, team.id, 1, "progress", 15, T0)
        t = await repo.reset_demo(db, team.id)
        return t, await repo.get_mascot(db, team.id), await repo.last_action_at(db, team.id, 1, "progress")
    t, m, last = run_db(body)
    assert t.end == T0 + timedelta(days=28)
    assert t.demo_offset_hours == 0 and t.demo_speed == 1.0
    assert m.hp == 100 and m.skin_level == 1 and m.revive_count == 0 and m.acceptance_since is None
    assert last is None


def test_delete_team_cascades():
    async def body(db):
        team = await make_team(db)
        await repo.ensure_member(db, team.id, 1, "가", T0)
        await repo.delete_team(db, team.id)
        return await repo.get_mascot(db, team.id), await repo.count_members(db, team.id)
    m, n = run_db(body)
    assert m is None and n == 0

def test_stuck_request_claim_once():
    async def body(db):
        team = await make_team(db)
        rid = await repo.create_stuck_request(db, team.id, 1, "버그", T0)
        first = await repo.claim_stuck_request(db, rid, 2, T0)
        second = await repo.claim_stuck_request(db, rid, 3, T0)
        return first, second, await repo.get_stuck_request(db, rid)
    first, second, req = run_db(body)
    assert first is True and second is False
    assert req.helper_id == 2 and req.status == "helped" and req.resolved_at == T0

def test_update_period_becomes_reset_baseline():
    new_start = T0 + timedelta(days=1)
    new_end = T0 + timedelta(days=40)                      # 기간 39일
    async def body(db):
        team = await make_team(db)
        await repo.update_team_period(db, team.id, new_start, new_end)
        # 데모로 마감을 당긴 상태 (기간 39일은 그대로 유지)
        await repo.update_team_demo(
            db, team.id, start=T0 - timedelta(days=36), end=T0 + timedelta(days=3))
        return await repo.reset_demo(db, team.id)
    t = run_db(body)
    assert t.start == new_start and t.end == new_end

def test_vote_roundtrip_and_close():
    deadline = T0 + timedelta(hours=1)
    async def body(db):
        team = await make_team(db)
        vid = await repo.create_vote(
            db, team_id=team.id, creator_id=1, title="회의 시간",
            options=["월 10시", "화 14시"], allow_multiple=True, deadline=deadline, created_at=T0)
        await repo.set_user_choices(db, vid, 1, {0, 1})
        await repo.set_user_choices(db, vid, 1, {1})            # 통째로 교체
        await repo.set_user_choices(db, vid, 2, {0})
        vote = await repo.get_vote(db, vid)
        resp = await repo.get_vote_responses(db, vid)
        due_before = await repo.list_due_votes(db, T0)
        due_after = await repo.list_due_votes(db, deadline)
        first = await repo.close_vote(db, vid, deadline)
        second = await repo.close_vote(db, vid, deadline)
        return vid, vote, resp, due_before, due_after, first, second
    vid, vote, resp, due_before, due_after, first, second = run_db(body)
    assert vote.options == ("월 10시", "화 14시") and vote.allow_multiple is True
    assert sorted(resp) == [(1, 1), (2, 0)]
    assert due_before == [] and [v.id for v in due_after] == [vid]
    assert first is True and second is False