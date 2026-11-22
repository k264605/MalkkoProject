# cogs/meeting_cmd.py
from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.common import announce, needs_announce, settle
from config import utcnow
from core.actions import ActionKind, apply_action, cooldown_remaining, is_allowed
from core.voting import (
    is_everyone, parse_deadline, tally, toggle_choice, voter_set, voters_by_option, winners,
)
from db import repo
from db.repo import VoteRow
from ui.embeds import build_vote_card, card_kwargs
from ui.translator import STAGE_KO

log = logging.getLogger("malkko.vote")
NO_MENTIONS = discord.AllowedMentions.none()


def _fmt_wait(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60) + 1
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h else f"{m}분"


async def render_vote(db, vote: VoteRow, closed: bool = False):
    """DB의 현재 응답으로 투표 카드를 만든다. (카드, 투표한 사람들, 등록된 팀원 수)"""
    responses = await repo.get_vote_responses(db, vote.id)
    voters = voter_set(responses)
    member_count = await repo.count_members(db, vote.team_id)
    card = build_vote_card(
        vote, tally(len(vote.options), responses), voters_by_option(responses),
        len(voters), member_count, closed=closed)
    return card, voters, member_count


class VoteButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"malkko:vote:(?P<vid>[0-9]+):(?P<idx>[0-9]+)",
):
    """투표 번호 버튼. 투표·항목마다 custom_id가 달라서 봇을 재시작해도 계속 동작한다."""

    def __init__(self, vote_id: int, index: int, label: str | None = None) -> None:
        super().__init__(discord.ui.Button(
            label=label or f"{index + 1}번", style=discord.ButtonStyle.primary,
            custom_id=f"malkko:vote:{vote_id}:{index}",
        ))
        self.vote_id = vote_id
        self.index = index

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match, /):
        return cls(int(match["vid"]), int(match["idx"]), label=item.label)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        db = bot.db
        user = interaction.user

        vote = await repo.get_vote(db, self.vote_id)
        team = await repo.get_team(db, vote.team_id) if vote else None
        if vote is None or team is None:
            await interaction.response.send_message("이 투표는 더 이상 없어요.", ephemeral=True)
            return

        refused: str | None = None
        notes: list[str] = []
        new: set[int] = set()
        everyone_bonus = False
        decay_change = None
        m = m_start = m_before_bonus = None
        now = team.now()

        async with repo.team_lock(team.id):
            vote = await repo.get_vote(db, self.vote_id)          # 락 안에서 다시 확인
            if vote is None or vote.closed or utcnow() >= vote.deadline:
                refused = "이미 마감된 투표예요."
            else:
                now = team.now()
                await repo.ensure_member(db, team.id, user.id, user.display_name, now)
                current = await repo.get_user_choices(db, vote.id, user.id)
                new = toggle_choice(current, self.index, vote.allow_multiple)
                await repo.set_user_choices(db, vote.id, user.id, new)

                member_count = await repo.count_members(db, team.id)
                voters = voter_set(await repo.get_vote_responses(db, vote.id))
                m, decay_change = await settle(db, team, now, save=True, lock=False)
                m_start = m

                # 1) 처음 투표하면 +10 (투표당 한 번, 1시간에 한 번)
                kind = ActionKind.VOTE
                if new and not await repo.has_action(db, team.id, user.id, kind, f"vote:{vote.id}"):
                    if not is_allowed(m, kind):
                        notes.append("말꼬가 수용 단계라 체력 회복은 없어요 (`/진행`으로 부활 미션!)")
                    else:
                        wait = cooldown_remaining(
                            kind, await repo.last_action_at(db, team.id, user.id, kind), now)
                        if wait.total_seconds() > 0:
                            notes.append(f"체력 보상은 **{_fmt_wait(wait)}** 뒤부터 받을 수 있어요 (이번엔 없어요)")
                        else:
                            change = apply_action(m, kind, now)
                            await repo.add_action(
                                db, team.id, user.id, kind,
                                change.hp_delta if change else 0.0, now, f"vote:{vote.id}")
                            if change:
                                m = change.after
                                await repo.save_mascot(db, team.id, m)
                                notes.append(f"체력 +{int(change.hp_delta)}")

                # 2) 전원이 투표하면 +20 (투표당 한 번)
                kind_all = ActionKind.VOTE_ALL
                if (not vote.all_awarded and is_everyone(len(voters), member_count)
                        and is_allowed(m, kind_all)):
                    m_before_bonus = m
                    change = apply_action(m, kind_all, now)
                    await repo.add_action(
                        db, team.id, user.id, kind_all,
                        change.hp_delta if change else 0.0, now, f"vote_all:{vote.id}")
                    if change:
                        m = change.after
                        await repo.save_mascot(db, team.id, m)
                    await repo.mark_all_awarded(db, vote.id)
                    everyone_bonus = True

                if m.stage != m_start.stage:
                    notes.append(f"📈 {STAGE_KO[m_start.stage]} → {STAGE_KO[m.stage]}")

        if refused:
            await interaction.response.send_message(refused, ephemeral=True)
            return

        # 카드를 최신 상태로 갱신하고, 개인 안내는 나만 보이게 보낸다
        card, _, _ = await render_vote(db, vote)
        await interaction.response.edit_message(embed=card)

        if not new:
            personal = "🗑️ 투표를 취소했어요."
        else:
            picked = ", ".join(f"{i + 1}번 {vote.options[i]}" for i in sorted(new))
            personal = f"✅ 투표했어요: {picked}"
        if notes:
            personal += "\n" + " · ".join(notes)
        await interaction.followup.send(personal, ephemeral=True)

        if everyone_bonus:
            await interaction.followup.send(
                content=(f"🎉 **전원 투표 완료!** 「{vote.title}」 "
                         f"체력 {int(m_before_bonus.hp)} → {int(m.hp)}"),
                **card_kwargs(team, m, now, headline="다 같이 정해서 든든해!"),
            )

        if needs_announce(decay_change):
            await announce(bot, team, decay_change, now)


class MeetingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(VoteButton)
        self.close_due.start()

    async def cog_unload(self) -> None:
        self.close_due.cancel()
        self.bot.remove_dynamic_items(VoteButton)

    # ── 투표 만들기 ──────────────────────────────────
    @app_commands.command(name="meeting-vote", description="회의 시간 등 팀 투표를 만들어요")
    @app_commands.describe(
        title="투표 제목 (예: 주간 회의 시간)",
        option1="후보 1", option2="후보 2",
        deadline="마감 (예: 30분, 2시간, 18:00, 11-25 18:00)",
        multiple="여러 개 선택할 수 있게 할까요? (기본: 한 개만)",
        option3="후보 3 (선택)", option4="후보 4 (선택)", option5="후보 5 (선택)",
    )
    @app_commands.guild_only()
    async def meeting_vote(
        self, interaction: discord.Interaction,
        title: str, option1: str, option2: str, deadline: str, multiple: bool = False,
        option3: str | None = None, option4: str | None = None, option5: str | None = None,
    ) -> None:
        db = self.bot.db
        team = await repo.get_team_by_channel(db, interaction.channel_id)
        if team is None:
            await interaction.response.send_message(
                "이 채널에는 아직 말꼬가 없어요. `/말꼬-시작`으로 만들어 주세요.", ephemeral=True)
            return

        title = title.strip()
        options = [o.strip() for o in (option1, option2, option3, option4, option5) if o and o.strip()]
        error = None
        if not title or len(title) > 100:
            error = "제목은 1~100자로 적어 주세요."
        elif len(options) < 2:
            error = "후보는 2개 이상 필요해요."
        elif any(len(o) > 70 for o in options):
            error = "후보는 70자 이내로 적어 주세요."
        elif len(set(options)) != len(options):
            error = "같은 후보가 중복돼 있어요."

        now = utcnow()
        deadline_at = None
        if error is None:
            try:
                deadline_at = parse_deadline(deadline, now)
            except ValueError as e:
                error = str(e)
        if error is None:
            if deadline_at < now + timedelta(minutes=1):
                error = "마감은 지금부터 최소 1분 뒤여야 해요."
            elif deadline_at > now + timedelta(days=30):
                error = "마감은 30일 이내로 정해 주세요."
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        user = interaction.user
        await repo.ensure_member(db, team.id, user.id, user.display_name, team.now())
        vote_id = await repo.create_vote(
            db, team_id=team.id, creator_id=user.id, title=title, options=options,
            allow_multiple=multiple, deadline=deadline_at, created_at=now)
        vote = await repo.get_vote(db, vote_id)

        card, _, _ = await render_vote(db, vote)
        view = discord.ui.View(timeout=None)
        for i, label in enumerate(options):
            view.add_item(VoteButton(vote_id, i, label=f"{i + 1}. {label}"[:80]))
        await interaction.response.send_message(
            content=f"🗳️ {user.mention}님이 투표를 열었어요!",
            embed=card, view=view, allowed_mentions=NO_MENTIONS)
        try:
            msg = await interaction.original_response()
            await repo.set_vote_message(db, vote_id, msg.id)
        except discord.HTTPException:
            log.warning("투표 메시지 ID를 저장하지 못했습니다 (vote %s)", vote_id)

    # ── 마감 처리 (10초마다 확인) ─────────────────────
    @tasks.loop(seconds=10)
    async def close_due(self) -> None:
        try:
            due = await repo.list_due_votes(self.bot.db, utcnow())
        except Exception:
            log.exception("마감할 투표를 불러오지 못했습니다")
            return
        for vote in due:
            try:
                await self._close(vote)
            except Exception:
                log.exception("투표 마감 처리 오류 (vote %s)", vote.id)

    @close_due.before_loop
    async def _before_close_due(self) -> None:
        await self.bot.wait_until_ready()

    async def _close(self, vote: VoteRow) -> None:
        db = self.bot.db
        team = await repo.get_team(db, vote.team_id)
        if team is None:
            return
        async with repo.team_lock(team.id):
            if not await repo.close_vote(db, vote.id, utcnow()):      # 이미 다른 곳에서 닫음
                return

        card, voters, _ = await render_vote(db, vote, closed=True)
        counts = tally(len(vote.options), await repo.get_vote_responses(db, vote.id))
        top = winners(counts)
        if not top:
            result = f"🏁 **{vote.title}** 투표가 마감됐어요. 아무도 투표하지 않았어요."
        elif len(top) == 1:
            result = (f"🏁 **{vote.title}** 투표 결과: **{vote.options[top[0]]}** "
                      f"({counts[top[0]]}명, 참여 {len(voters)}명)")
        else:
            names = ", ".join(f"**{vote.options[i]}**" for i in top)
            result = (f"🏁 **{vote.title}** 투표 결과: 공동 1위 {names} "
                      f"({counts[top[0]]}명씩, 참여 {len(voters)}명)")

        channel = self.bot.get_channel(team.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(team.channel_id)
            except discord.HTTPException:
                log.warning("투표 채널을 찾을 수 없음: vote=%s", vote.id)
                return

        message = None
        if vote.message_id:
            try:
                message = await channel.fetch_message(vote.message_id)
                await message.edit(embed=card, view=None)        # 버튼 제거, 결과 표시
            except discord.HTTPException:
                message = None
        try:
            if message is not None:
                await message.reply(result, mention_author=False)
            else:
                await channel.send(result)
        except discord.HTTPException:
            log.warning("투표 결과 전송 실패: vote=%s", vote.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MeetingCog(bot))