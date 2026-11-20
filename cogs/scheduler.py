# cogs/scheduler.py
from __future__ import annotations

import logging

from discord.ext import commands, tasks

from cogs.common import announce, needs_announce, settle
from db import repo

log = logging.getLogger("malkko.scheduler")

INTERVAL_SECONDS = 10


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._ticks = 0

    async def cog_load(self) -> None:
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    @tasks.loop(seconds=INTERVAL_SECONDS)
    async def tick(self) -> None:
        db = self.bot.db
        try:
            teams = await repo.list_teams(db)
        except Exception:
            log.exception("팀 목록을 불러오지 못했습니다")
            return

        for team in teams:
            try:
                now = team.now()
                _, change = await settle(db, team, now, save=True)
                if needs_announce(change):
                    await announce(self.bot, team, change, now)
            except Exception:
                log.exception("스케줄러 오류 (team %s)", team.id)

        self._ticks += 1
        if self._ticks % 6 == 0:                       # 1분마다 생존 신호
            log.info("scheduler alive: %d team(s)", len(teams))

    @tick.before_loop
    async def _before_tick(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))