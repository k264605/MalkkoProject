# cogs/demo.py
from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from cogs.common import announce, needs_announce, revive_info, settle
from db import repo
from db.repo import TeamRow
from ui.embeds import build_status_card, describe_change


class DemoCog(commands.Cog):
    # 서버 관리 권한이 있는 사람에게만 보인다 (심사위원이 실수로 누르지 않게)
    demo = app_commands.Group(
        name="demo", description="시연용 도구", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _team(self, interaction: discord.Interaction) -> TeamRow | None:
        team = await repo.get_team_by_channel(self.bot.db, interaction.channel_id)
        if team is None:
            await interaction.response.send_message(
                "이 채널에는 아직 말꼬가 없어요. `/말꼬-시작`으로 만들어 주세요.", ephemeral=True)
        return team

    @demo.command(name="skip", description="지정한 시간만큼 지난 것으로 처리해요")
    @app_commands.describe(hours="건너뛸 시간 (예: 24)")
    async def skip(
        self, interaction: discord.Interaction, hours: app_commands.Range[float, 0.01, 8760.0],
    ) -> None:
        team = await self._team(interaction)
        if team is None:
            return
        await interaction.response.defer()
        db = self.bot.db

        await repo.update_team_demo(
            db, team.id, demo_offset_hours=team.demo_offset_hours + hours)
        team = await repo.get_team(db, team.id)
        now = team.now()
        m, change = await settle(db, team, now, save=True)

        text = f"⏩ **{hours:g}시간**을 건너뛰었어요."
        if summary := describe_change(change):
            text += f"\n{summary}"
        await interaction.followup.send(content=text)

        if needs_announce(change):
            await announce(self.bot, team, change, now)
        else:
            revive = await revive_info(db, team, m)
            await interaction.followup.send(embed=build_status_card(team, m, now, revive))

    @demo.command(name="deadline", description="마감을 앞당겨서 가속 구간을 바로 보여줘요")
    @app_commands.describe(days="마감까지 남길 일수 (예: 2)")
    async def deadline(
        self, interaction: discord.Interaction, days: app_commands.Range[float, 0.0, 3650.0],
    ) -> None:
        team = await self._team(interaction)
        if team is None:
            return
        await interaction.response.defer()
        db = self.bot.db

        # 1) 지금까지의 감소를 기존 기준으로 먼저 확정한다
        team_old, now_old = team, team.now()
        _, change1 = await settle(db, team_old, now_old, save=True)

        # 2) 기간(전체 길이)은 그대로 두고 시작·마감을 함께 옮긴다 -> 남은 비율이 바로 줄어든다
        duration = team_old.end - team_old.start
        new_end = now_old + timedelta(days=days)
        await repo.update_team_demo(db, team_old.id, start=new_end - duration, end=new_end)

        # 3) 새 기준을 반영한다 (가속 단계 갱신). now를 새로 구해야 last_decay_at보다 뒤가 된다
        team = await repo.get_team(db, team_old.id)
        now = team.now()
        m, change2 = await settle(db, team, now, save=True)

        text = f"📅 마감을 **{days:g}일 뒤**로 당겼어요."
        summary = " · ".join(s for s in (describe_change(change1), describe_change(change2)) if s)
        if summary:
            text += f"\n{summary}"
        await interaction.followup.send(content=text)

        announced = False
        if needs_announce(change1):
            await announce(self.bot, team_old, change1, now_old)
            announced = True
        if needs_announce(change2):
            await announce(self.bot, team, change2, now)
            announced = True
        if not announced:
            revive = await revive_info(db, team, m)
            await interaction.followup.send(embed=build_status_card(team, m, now, revive))

    @demo.command(name="reset", description="체력 100, 정상, 가상 시간을 처음 상태로 되돌려요")
    async def reset(self, interaction: discord.Interaction) -> None:
        team = await self._team(interaction)
        if team is None:
            return
        await interaction.response.defer()
        db = self.bot.db
        async with repo.team_lock(team.id):
            team = await repo.reset_demo(db, team.id)
        now = team.now()
        m = await repo.get_mascot(db, team.id)
        await interaction.followup.send(
            content="🔄 데모를 초기화했어요.",
            embed=build_status_card(team, m, now, headline="처음부터 다시 시작해볼까?"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DemoCog(bot))