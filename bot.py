# bot.py
from __future__ import annotations

import logging

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import BASE_DIR, settings

from ui.translator import KoTranslator

log = logging.getLogger("malkko")

# 만드는 대로 여기에 추가한다. (예: "cogs.setup_cmd")
COGS: list[str] = [
    "cogs.setup_cmd", "cogs.demo", "cogs.scheduler", "cogs.actions_cmd", "cogs.listener",
]


class MalkkoBot(commands.Bot):
    db: aiosqlite.Connection

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # 잡담 분류용 (포털에서도 켜야 함)
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

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

        await self.tree.set_translator(KoTranslator())  # ← 추가 (sync보다 먼저)

        # 3) 슬래시 명령 동기화 (개발 서버에는 즉시 반영)
        if settings.dev_guild_id:
            guild = discord.Object(id=settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info("synced %d commands", len(synced))

    async def on_ready(self) -> None:
        log.info("logged in as %s (id=%s)", self.user, self.user.id)

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
    discord.utils.setup_logging(level=logging.INFO)
    bot.run(settings.token, log_handler=None)