# cogs/actions_cmd.py
from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from cogs.common import announce, needs_announce, settle
from core.actions import ActionKind, apply_action, cooldown_remaining, motion_for, revive_required
from core.messages import REVIVE_LINE, thanks_line
from core.state import Stage
from db import repo
from ui.embeds import MOTION_EMOJI, card_kwargs
from ui.translator import STAGE_KO


def fmt_wait(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60) + 1
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h else f"{m}분"


class ActionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="progress", description="오늘의 진행 상황을 한 줄로 공유해요")
    @app_commands.describe(content="진행한 내용을 한 줄로 (예: 로그인 API 완성)")
    @app_commands.guild_only()
    async def progress(
        self, interaction: discord.Interaction, content: app_commands.Range[str, 1, 200],
    ) -> None:
        db = self.bot.db
        team = await repo.get_team_by_channel(db, interaction.channel_id)
        if team is None:
            await interaction.response.send_message(
                "이 채널에는 아직 말꼬가 없어요. `/말꼬-시작`으로 만들어 주세요.", ephemeral=True)
            return

        user = interaction.user
        kind = ActionKind.PROGRESS
        sharers: frozenset[int] = frozenset()
        member_count = 1
        change = None

        async with repo.team_lock(team.id):
            now = team.now()
            # 1) 지금까지의 감소를 먼저 반영 (안 하면 오래된 체력에 회복이 더해진다)
            m, decay_change = await settle(db, team, now, save=True, lock=False)

            # 2) 쿨다운은 기록하기 전에 확인 (방금 기록한 자기 자신이 걸리지 않게)
            last = await repo.last_action_at(db, team.id, user.id, kind)
            remaining = cooldown_remaining(kind, last, now)

            if remaining.total_seconds() <= 0:
                # 3) 팀원 등록 (부활 과반이 등록된 인원 기준이라 먼저 한다)
                await repo.ensure_member(db, team.id, user.id, user.display_name, now)
                member_count = await repo.count_members(db, team.id)
                if m.stage is Stage.ACCEPTANCE and m.acceptance_since is not None:
                    sharers = await repo.sharers_since(db, team.id, m.acceptance_since)

                # 4) 코어 계산 -> 5) 기록과 저장
                change = apply_action(
                    m, kind, now, actor_id=user.id, sharers=sharers, member_count=member_count)
                await repo.add_action(
                    db, team.id, user.id, kind, change.hp_delta if change else 0.0, now, content)
                if change:
                    await repo.save_mascot(db, team.id, change.after)

        # 감소로 단계가 바뀐 경우의 알림 (락 밖에서)
        if needs_announce(decay_change):
            await announce(self.bot, team, decay_change, now)

        if remaining.total_seconds() > 0:
            await interaction.response.send_message(
                f"⏳ 진행 공유는 6시간에 한 번만 가능해요. **{fmt_wait(remaining)}** 뒤에 다시 해주세요.",
                ephemeral=True)
            return

        # 6) 결과 안내
        new_m = change.after if change else m
        need = revive_required(member_count)
        revive = None
        headline = None

        if change is not None and change.revived:
            text = f"✨ **부활!** 팀원 {len(sharers | {user.id})}/{need}명이 진행을 공유했어요."
            headline = REVIVE_LINE
        elif m.stage is Stage.ACCEPTANCE:
            done = len(sharers | {user.id})
            if user.id in sharers:
                text = f"🕯️ 이미 부활 미션에 참여했어요. 다른 팀원을 기다려요! ({done}/{need}명)"
            else:
                text = f"🕯️ {user.mention}님이 진행을 공유했어요. 부활 미션 {done}/{need}명"
            revive = (done, need)
        else:
            assert change is not None
            emoji = MOTION_EMOJI[motion_for(change)]
            text = f"{emoji} {user.mention}님이 진행을 공유했어요! 체력 {int(m.hp)} → {int(new_m.hp)}"
            if change.stage_changed:
                text += f"\n📈 {STAGE_KO[m.stage]} → {STAGE_KO[new_m.stage]}"
            headline = thanks_line()

        kw = card_kwargs(team, new_m, now, revive, headline=headline)
        await interaction.response.send_message(
            content=f"{text}\n> {content}",
            allowed_mentions=discord.AllowedMentions.none(),
            **kw,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ActionsCog(bot))