# cogs/settings_cmd.py
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.common import announce, needs_announce, settle
from cogs.setup_cmd import parse_date
from config import kst_end_of_day, kst_start_of_day
from db import repo
from ui.embeds import build_settings_card

NO_MENTIONS = discord.AllowedMentions.none()


class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="settings", description="말꼬의 시작일·마감일을 보거나 바꿔요")
    @app_commands.describe(
        start_date="새 시작일 (예: 2026-11-20)", end_date="새 마감일 (예: 2026-12-20)",
    )
    @app_commands.guild_only()
    async def settings(
        self, interaction: discord.Interaction,
        start_date: str | None = None, end_date: str | None = None,
    ) -> None:
        db = self.bot.db
        team = await repo.get_team_by_channel(db, interaction.channel_id)
        if team is None:
            await interaction.response.send_message(
                "이 채널에는 아직 말꼬가 없어요. `/말꼬-시작`으로 만들어 주세요.", ephemeral=True)
            return

        # 값을 안 넣으면 현재 설정만 보여준다 (나만 보임)
        if start_date is None and end_date is None:
            await interaction.response.send_message(
                embed=build_settings_card(team, team.now()), ephemeral=True)
            return

        if team.demo_offset_hours or team.demo_speed != 1.0:
            await interaction.response.send_message(
                "데모 모드(시간 건너뛰기) 중에는 기간을 바꿀 수 없어요. "
                "`/데모 초기화` 후에 바꿔 주세요.", ephemeral=True)
            return

        try:
            new_start = kst_start_of_day(parse_date(start_date)) if start_date else team.start
            new_end = kst_end_of_day(parse_date(end_date)) if end_date else team.end
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        if new_end <= new_start:
            await interaction.response.send_message(
                "마감일은 시작일과 같거나 이후여야 해요.", ephemeral=True)
            return
        if (new_start, new_end) == (team.start, team.end):
            await interaction.response.send_message("이미 같은 설정이에요.", ephemeral=True)
            return
        if new_end <= team.now():
            await interaction.response.send_message(
                "마감일이 이미 지났어요. 오늘 이후 날짜로 정해 주세요.", ephemeral=True)
            return

        old_team = team
        async with repo.team_lock(team.id):
            # 1) 기존 기간 기준으로 지금까지의 감소를 먼저 확정한다 (과거가 새 기준으로 다시 계산되지 않게)
            now_old = team.now()
            _, change1 = await settle(db, team, now_old, save=True, lock=False)

            # 2) 기간 변경 (원래 마감일도 같이 갱신)
            await repo.update_team_period(db, team.id, new_start, new_end)

            # 3) 새 기간 기준으로 가속 단계를 갱신한다. now를 새로 구해야 last_decay_at보다 뒤가 된다
            team = await repo.get_team(db, team.id)
            now = team.now()
            _, change2 = await settle(db, team, now, save=True, lock=False)

        await interaction.response.send_message(
            content=f"⚙️ {interaction.user.mention}님이 기간을 변경했어요.",
            embed=build_settings_card(team, now, old=old_team, old_now=now_old),
            allowed_mentions=NO_MENTIONS,
        )

        # 변경 때문에 단계가 바뀌거나 가속 구간에 들어갔다면 알림 (응답을 먼저 보낸 뒤)
        for change, t, n in ((change1, old_team, now_old), (change2, team, now)):
            if needs_announce(change):
                await announce(self.bot, t, change, n)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))