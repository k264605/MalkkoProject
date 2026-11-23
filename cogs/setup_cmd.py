# cogs/setup_cmd.py
from __future__ import annotations

import re
import sqlite3
from datetime import date

import discord
from discord import app_commands
from discord.ext import commands

from cogs.common import revive_info, settle
from config import KST, kst_end_of_day, kst_start_of_day, utcnow
from db import repo
from ui.embeds import card_kwargs


def parse_date(text: str) -> date:
    """'2026-12-20', '2026/12/20', '2026.12.20', '12-20'(올해)을 받는다."""
    try:
        nums = [int(p) for p in re.split(r"[-/.]", text.strip())]
        if len(nums) == 2:
            nums = [utcnow().astimezone(KST).year, *nums]
        if len(nums) != 3:
            raise ValueError
        return date(*nums)
    except ValueError:
        raise ValueError(f"날짜 형식이 올바르지 않아요: {text!r} (예: 2026-12-20)") from None


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="mascotstart", description="이 채널에 말꼬를 만들어요")
    @app_commands.describe(
        name="캐릭터 이름", end_date="마감일 (예: 2026-12-20)", start_date="시작일 (비우면 오늘)",
    )
    @app_commands.guild_only()
    async def mascotstart(
        self, interaction: discord.Interaction, name: str, end_date: str, start_date: str | None = None,
    ) -> None:
        today = utcnow().astimezone(KST).date()
        try:
            end = parse_date(end_date)
            start = parse_date(start_date) if start_date else today
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        if end < start or end < today:
            await interaction.response.send_message(
                "마감일은 시작일 이후, 그리고 오늘 이후여야 해요.", ephemeral=True)
            return

        db = self.bot.db
        if await repo.get_team_by_channel(db, interaction.channel_id):
            await interaction.response.send_message(
                "이 채널에는 이미 말꼬가 있어요. `/상태`로 확인해 보세요.", ephemeral=True)
            return

        # 결과 카드에 이미지가 붙어서 업로드가 길어질 수 있다. 3초 제한에 걸리지 않게 먼저 응답해 둔다
        await interaction.response.defer()

        try:
            team = await repo.create_team(
                db, guild_id=interaction.guild_id, channel_id=interaction.channel_id,
                name=name.strip() or "말꼬",
                start=kst_start_of_day(start), end=kst_end_of_day(end), created_at=utcnow(),
            )
        except sqlite3.IntegrityError:
            # 위에서 확인한 뒤 같은 채널에 동시에 만들어진 드문 경우
            await interaction.followup.send("이 채널에는 이미 말꼬가 있어요.")
            return

        now = team.now()
        await repo.ensure_member(
            db, team.id, interaction.user.id, interaction.user.display_name, now)
        m = await repo.get_mascot(db, team.id)
        kw = card_kwargs(
            team, m, now, headline=f"안녕! 나는 {team.name}이야. 우리 팀 잘 부탁해!")
        await interaction.followup.send(
            content="🎉 이 채널의 말꼬가 태어났어요!", **kw)

    @app_commands.command(name="status", description="말꼬의 현재 상태를 보여줘요")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        team = await repo.get_team_by_channel(db, interaction.channel_id)
        if team is None:
            await interaction.response.send_message(
                "이 채널에는 아직 말꼬가 없어요. `/말꼬-시작`으로 만들어 주세요.", ephemeral=True)
            return
        await interaction.response.defer()      # 이미지 업로드가 길어져도 3초 제한에 걸리지 않게
        now = team.now()
        m, _ = await settle(db, team, now, save=False)
        revive = await revive_info(db, team, m)
        await interaction.followup.send(**card_kwargs(team, m, now, revive))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))