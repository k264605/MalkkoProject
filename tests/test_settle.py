import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import aiosqlite

from cogs.common import settle
from config import BASE_DIR
from db import repo

UTC = timezone.utc
T0 = datetime(2026, 11, 1, tzinfo=UTC)
END = T0 + timedelta(days=28)            # 4주 프로젝트
SCHEMA = BASE_DIR / "db" / "schema.sql"


def test_extending_deadline_after_it_passed_keeps_hp():
    """마감 3일 뒤에 마감을 늘려도, 마감 뒤 3일이 새 기준으로 한꺼번에 깎이지 않는다."""
    async def main():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA.read_text(encoding="utf-8"))
        try:
            team = await repo.create_team(
                db, guild_id=1, channel_id=10, name="말꼬", start=T0, end=END, created_at=T0)
            m = await repo.get_mascot(db, team.id)
            await repo.save_mascot(db, team.id, replace(m, hp=60.0, speed_tier=2.0, last_decay_at=END))

            # 마감 순간 체력 60. 스케줄러처럼 마감 1분 뒤, 마감 3일 뒤에 차례로 settle
            await settle(db, team, END + timedelta(minutes=1), save=True)
            now = END + timedelta(days=3)
            m, _ = await settle(db, team, now, save=True)
            assert m.hp == 60.0 and m.last_decay_at == now      # 줄어든 건 없어도 시각은 남긴다

            # /설정처럼: 마감을 2주 뒤로 늘리고 새 기준으로 settle
            await repo.update_team_period(db, team.id, T0, now + timedelta(days=14))
            team = await repo.get_team(db, team.id)
            m, _ = await settle(db, team, now + timedelta(minutes=1), save=True)
            return m
        finally:
            await db.close()

    m = asyncio.run(main())
    assert m.hp > 59.9          # 1분치만 줄어야 한다 (수정 전에는 3일치가 한꺼번에 깎임)