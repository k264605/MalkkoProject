# cogs/stuck_cmd.py
from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from cogs.common import announce, needs_announce, settle
from core.actions import ActionKind, apply_action, cooldown_remaining, is_allowed, motion_for
from db import repo
from ui.embeds import MOTION_EMOJI, build_stuck_card, card_kwargs
from ui.translator import STAGE_KO

log = logging.getLogger("malkko.stuck")
NO_MENTIONS = discord.AllowedMentions.none()


def _fmt_wait(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60) + 1
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h else f"{m}분"


class StuckHelpButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"malkko:stuck:help:(?P<id>[0-9]+)",
):
    """🙋 도와줄게 버튼. 요청마다 custom_id가 달라서 봇을 재시작해도 계속 동작한다."""

    def __init__(self, request_id: int) -> None:
        super().__init__(discord.ui.Button(
            label="도와줄게", emoji="🙋", style=discord.ButtonStyle.success,
            custom_id=f"malkko:stuck:help:{request_id}",
        ))
        self.request_id = request_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match, /):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        db = bot.db
        user = interaction.user

        req = await repo.get_stuck_request(db, self.request_id)
        team = await repo.get_team(db, req.team_id) if req else None
        if req is None or team is None:
            await interaction.response.send_message("이 요청은 더 이상 없어요.", ephemeral=True)
            return

        refused: str | None = None
        change = None
        decay_change = None
        m = None
        now = team.now()

        async with repo.team_lock(team.id):
            req = await repo.get_stuck_request(db, self.request_id)      # 락 안에서 다시 확인
            if req is None:
                refused = "이 요청은 더 이상 없어요."
            elif req.status != "open":
                refused = "이미 다른 팀원이 도와주기로 한 요청이에요."
            elif req.requester_id == user.id:
                refused = "내가 올린 요청에는 도와줄게를 누를 수 없어요."
            else:
                now = team.now()
                m, decay_change = await settle(db, team, now, save=True, lock=False)
                if not is_allowed(m, ActionKind.STUCK_HELP):
                    refused = "말꼬가 지금 수용 단계예요. 부활 미션(`/진행`)만 할 수 있어요."
                elif not await repo.claim_stuck_request(db, req.id, user.id, now):
                    refused = "이미 다른 팀원이 도와주기로 한 요청이에요."
                else:
                    await repo.ensure_member(db, team.id, user.id, user.display_name, now)
                    change = apply_action(m, ActionKind.STUCK_HELP, now)
                    await repo.add_action(
                        db, team.id, user.id, ActionKind.STUCK_HELP,
                        change.hp_delta if change else 0.0, now, f"help:{req.id}")
                    if change:
                        await repo.save_mascot(db, team.id, change.after)

        if refused:
            await interaction.response.send_message(refused, ephemeral=True)
        else:
            assert change is not None and m is not None
            # 카드를 '도움 받는 중'으로 바꾸고 버튼을 끈다
            done = discord.ui.View(timeout=None)
            done.add_item(discord.ui.Button(
                label="도움 받는 중", emoji="✅", style=discord.ButtonStyle.secondary, disabled=True))
            await interaction.response.edit_message(
                embed=build_stuck_card(req.requester_id, req.content, helper_id=user.id), view=done)

            new_m = change.after
            text = (f"{MOTION_EMOJI[motion_for(change)]} {user.mention}님이 "
                    f"<@{req.requester_id}>님을 도와주기로 했어요! "
                    f"체력 {int(m.hp)} → {int(new_m.hp)}")
            if change.stage_changed:
                text += f"\n📈 {STAGE_KO[m.stage]} → {STAGE_KO[new_m.stage]}"
            await interaction.followup.send(
                content=text,
                allowed_mentions=NO_MENTIONS,
                **card_kwargs(team, new_m, now, headline="도와줘서 고마워! 기운이 나!"),
            )

        # 감소로 단계가 바뀐 경우의 알림 (응답을 먼저 보낸 뒤)
        if needs_announce(decay_change):
            await announce(bot, team, decay_change, now)


class StuckCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(StuckHelpButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(StuckHelpButton)

    @app_commands.command(name="stuck", description="막힌 내용을 팀원에게 공유하고 도움을 요청해요")
    @app_commands.describe(content="막힌 내용 (예: 로그인 API에서 401이 계속 나요)")
    @app_commands.guild_only()
    async def stuck(
        self, interaction: discord.Interaction, content: app_commands.Range[str, 1, 300],
    ) -> None:
        db = self.bot.db
        team = await repo.get_team_by_channel(db, interaction.channel_id)
        if team is None:
            await interaction.response.send_message(
                "이 채널에는 아직 말꼬가 없어요. `/말꼬-시작`으로 만들어 주세요.", ephemeral=True)
            return

        user = interaction.user
        kind = ActionKind.STUCK_REQUEST
        refused: str | None = None
        change = None
        request_id = 0

        async with repo.team_lock(team.id):
            now = team.now()
            m, decay_change = await settle(db, team, now, save=True, lock=False)

            if not is_allowed(m, kind):
                refused = "말꼬가 지금 수용 단계예요. 부활 미션(`/진행`)만 할 수 있어요."
            else:
                last = await repo.last_action_at(db, team.id, user.id, kind)
                remaining = cooldown_remaining(kind, last, now)
                if remaining.total_seconds() > 0:
                    refused = (f"⏳ 막힘 요청은 연달아 보낼 수 없어요. "
                               f"**{_fmt_wait(remaining)}** 뒤에 다시 해주세요.")

            if refused is None:
                await repo.ensure_member(db, team.id, user.id, user.display_name, now)
                change = apply_action(m, kind, now)                              # 요청 +5
                await repo.add_action(
                    db, team.id, user.id, kind, change.hp_delta if change else 0.0, now, content)
                if change:
                    await repo.save_mascot(db, team.id, change.after)
                request_id = await repo.create_stuck_request(db, team.id, user.id, content, now)

        if refused:
            await interaction.response.send_message(refused, ephemeral=True)
        else:
            assert change is not None
            new_m = change.after
            view = discord.ui.View(timeout=None)
            view.add_item(StuckHelpButton(request_id))
            text = (f"🆘 {user.mention}님이 막혔어요! "
                    f"체력 {int(m.hp)} → {int(new_m.hp)} (요청 +{int(change.hp_delta)})")
            if change.stage_changed:
                text += f"\n📈 {STAGE_KO[m.stage]} → {STAGE_KO[new_m.stage]}"
            await interaction.response.send_message(
                content=text, embed=build_stuck_card(user.id, content),
                view=view, allowed_mentions=NO_MENTIONS)
            try:
                msg = await interaction.original_response()
                await repo.set_stuck_message(db, request_id, msg.id)
            except discord.HTTPException:
                log.warning("요청 메시지 ID를 저장하지 못했습니다 (request %s)", request_id)

        if needs_announce(decay_change):
            await announce(self.bot, team, decay_change, now)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StuckCog(bot))