# bot.py
from __future__ import annotations

import logging

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import BASE_DIR, settings

from ui.images import check_assets
from ui.translator import KoTranslator

log = logging.getLogger("malkko")

COGS: list[str] = [
    "cogs.setup_cmd", "cogs.demo", "cogs.scheduler", "cogs.actions_cmd",
    "cogs.listener", "cogs.stuck_cmd", "cogs.settings_cmd", "cogs.meeting_cmd",
]


class MalkkoBot(commands.Bot):
    db: aiosqlite.Connection

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # 잡담 분류용 (포털에서도 켜야 함)
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self._guild_cleanup_done = False   # on_ready는 재연결 때마다 불리므로 한 번만 정리하려고

    async def setup_hook(self) -> None:
        # 1) DB 연결 (봇 전체가 연결 하나를 공유)
        self.db = await aiosqlite.connect(settings.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL;")
        await self.db.execute("PRAGMA foreign_keys=ON;")

        # schema.sql이 생기면 자동으로 실행 (CREATE TABLE IF NOT EXISTS 사용)
        schema = BASE_DIR / "db" / "schema.sql"
        if schema.exists():
            await self.db.executescript(schema.read_text(encoding="utf-8"))
        await self.db.commit()

        # 2) cog 로딩
        for ext in COGS:
            await self.load_extension(ext)
            log.info("loaded %s", ext)

        # 캐릭터 이미지 점검 (연결된 수, 빠진 단계, 2MB 초과를 로그로 알려준다)
        check_assets()

        await self.tree.set_translator(KoTranslator())  # ← 추가 (sync보다 먼저)

        # 3) 슬래시 명령 동기화 (실패해도 봇은 계속 실행)
        try:
            if settings.sync_scope == "guild":
                # 개발용: 한 서버에만 즉시 반영
                guild = discord.Object(id=settings.dev_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                self.tree.clear_commands(guild=None)  # 전역에 남은 같은 명령 정리 (두 번 뜨는 것 방지)
                await self.tree.sync()
                log.info("synced %d guild commands (dev), cleared global commands", len(synced))
            else:
                # 배포용: 봇이 들어간 모든 서버에서 사용
                synced = await self.tree.sync()
                log.info("synced %d global commands", len(synced))
                if settings.dev_guild_id:
                    # 예전에 개발 서버 전용으로 등록해 둔 같은 명령을 정리 (두 번 뜨는 것 방지)
                    guild = discord.Object(id=settings.dev_guild_id)
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    log.info("cleared old guild commands in %s", settings.dev_guild_id)
        except discord.HTTPException as e:
            log.error("명령 동기화 실패: %s (봇이 서버에 있는지, applications.commands scope로 초대했는지 확인)", e)

    async def on_ready(self) -> None:
        log.info("logged in as %s (id=%s)", self.user, self.user.id)
        # on_ready는 연결이 끊겼다 다시 붙을 때마다 불린다. 서버별 명령 정리는 실행당 한 번만 한다
        # (매번 하면 서버 수만큼 동기화 요청이 반복돼 디스코드 요청 제한에 걸릴 수 있다)
        if self._guild_cleanup_done or settings.dev_guild_id:
            return
        self._guild_cleanup_done = True
        for g in self.guilds:
            try:
                self.tree.clear_commands(guild=g)
                await self.tree.sync(guild=g)
            except discord.HTTPException as e:
                log.warning("서버 전용 명령 정리 실패: guild=%s (%s)", g.id, e)

    async def close(self) -> None:
        await super().close()  # cog(스케줄러) 먼저 정리
        await self.db.close()


bot = MalkkoBot()


# ── 임시 확인용 명령 (나중에 지워도 됨) ──────────────────
@bot.tree.command(name="ping", description="봇과 DB 연결 확인")
async def ping(interaction: discord.Interaction) -> None:
    async with bot.db.execute("SELECT 1") as cur:
        await cur.fetchone()
    ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"pong! 지연 {ms}ms, DB 정상")


if __name__ == "__main__":
    if not settings.token:
        raise SystemExit(".env에 DISCORD_TOKEN이 없습니다.")
    discord.utils.setup_logging(level=logging.INFO)
    bot.run(settings.token, log_handler=None)