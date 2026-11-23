import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite

from cogs.actions_cmd import ActionsCog
from cogs.setup_cmd import SetupCog
from config import BASE_DIR, utcnow
from db import repo

SCHEMA = BASE_DIR / "db" / "schema.sql"
CHANNEL = 10


def fake_interaction(user_id: int = 1):
    """디스코드 없이 명령어를 불러 보기 위한 가짜 interaction."""
    it = MagicMock()
    it.guild_id = 1
    it.channel_id = CHANNEL
    it.user = SimpleNamespace(id=user_id, display_name=f"user{user_id}", mention=f"<@{user_id}>")
    it.response.send_message = AsyncMock()
    it.response.defer = AsyncMock()
    it.followup.send = AsyncMock()
    return it


def close_files(it) -> None:
    for call in it.followup.send.await_args_list:      # 첨부 이미지 파일 닫기
        if "file" in call.kwargs:
            call.kwargs["file"].close()


def run_progress(calls):
    """calls: 차례로 /진행을 부를 user_id 목록. 각 호출의 interaction을 돌려준다."""
    async def main():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(SCHEMA.read_text(encoding="utf-8"))
        try:
            now = utcnow()
            await repo.create_team(
                db, guild_id=1, channel_id=CHANNEL, name="말꼬",
                start=now - timedelta(days=1), end=now + timedelta(days=27), created_at=now)
            cog = ActionsCog(SimpleNamespace(db=db))
            results = []
            for user_id in calls:
                it = fake_interaction(user_id)
                await ActionsCog.progress.callback(cog, it, "로그인 API 완성")
                close_files(it)
                results.append(it)
            return results
        finally:
            await db.close()
    return asyncio.run(main())


def test_progress_defers_then_sends_followup():
    (it,) = run_progress([1])
    # 3초 제한에 걸리지 않게 먼저 defer로 응답하고, 결과는 followup으로 보낸다
    it.response.defer.assert_awaited_once()
    it.response.send_message.assert_not_awaited()
    it.followup.send.assert_awaited_once()
    kwargs = it.followup.send.await_args.kwargs
    assert "진행을 공유했어요" in kwargs["content"] and "로그인 API 완성" in kwargs["content"]
    assert "embed" in kwargs


def test_progress_cooldown_is_private_and_not_deferred():
    first, second = run_progress([1, 1])
    first.response.defer.assert_awaited_once()
    # 6시간 안에 다시 쓰면: defer 없이 바로, 나만 보이게 안내한다
    second.response.defer.assert_not_awaited()
    second.followup.send.assert_not_awaited()
    second.response.send_message.assert_awaited_once()
    assert second.response.send_message.await_args.kwargs.get("ephemeral") is True
    assert "6시간" in second.response.send_message.await_args.args[0]


def run_setup(body):
    """빈 DB로 SetupCog를 만들어 body(cog)를 실행한다."""
    async def main():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(SCHEMA.read_text(encoding="utf-8"))
        try:
            return await body(SetupCog(SimpleNamespace(db=db)))
        finally:
            await db.close()
    return asyncio.run(main())


def test_mascotstart_and_status_defer_before_sending_card():
    async def body(cog):
        start = fake_interaction()
        await SetupCog.mascotstart.callback(cog, start, "말꼬", "2099-12-31")
        status = fake_interaction()
        await SetupCog.status.callback(cog, status)
        again = fake_interaction()
        await SetupCog.mascotstart.callback(cog, again, "말꼬", "2099-12-31")
        for it in (start, status, again):
            close_files(it)
        return start, status, again

    start, status, again = run_setup(body)
    for it in (start, status):                     # 카드(이미지)를 보내는 응답은 defer 후 followup
        it.response.defer.assert_awaited_once()
        it.response.send_message.assert_not_awaited()
        it.followup.send.assert_awaited_once()
        assert "embed" in it.followup.send.await_args.kwargs
    # 이미 말꼬가 있는 채널에서 다시 만들면: defer 없이 바로, 나만 보이게 안내
    again.response.defer.assert_not_awaited()
    assert again.response.send_message.await_args.kwargs.get("ephemeral") is True


def test_status_without_team_is_private_and_not_deferred():
    async def body(cog):
        it = fake_interaction()
        await SetupCog.status.callback(cog, it)
        return it

    it = run_setup(body)
    it.response.defer.assert_not_awaited()
    assert it.response.send_message.await_args.kwargs.get("ephemeral") is True
