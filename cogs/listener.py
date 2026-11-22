# cogs/listener.py
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core.classify import classify
from core.messages import nag_line
from core.policy import BotAction, Streak, decide, update_streak
from db import repo

log = logging.getLogger("malkko.listener")


class ListenerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._known: set[tuple[int, int]] = set()    # (team_id, user_id): 이미 등록 확인한 사람
        self._streaks: dict[int, Streak] = {}        # team_id -> 잡담 연속 횟수 (재시작하면 초기화)
        self._warned_intent = False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # 1) 봇 메시지, DM 무시
        if message.author.bot or message.guild is None:
            return
        db = self.bot.db
        team = await repo.get_team_by_channel(db, message.channel.id)
        if team is None:
            return

        # 내용이 통째로 비어 있으면 Message Content Intent가 꺼진 것일 수 있다 (한 번만 경고)
        if (not message.content and not self._warned_intent
                and not (message.attachments or message.embeds or message.stickers)):
            log.warning("메시지 내용이 비어 있습니다. 개발자 포털의 Message Content Intent를 확인하세요.")
            self._warned_intent = True

        now = team.now()

        # 2) 처음 보는 작성자면 팀원 등록
        key = (team.id, message.author.id)
        if key not in self._known:
            await repo.ensure_member(
                db, team.id, message.author.id, message.author.display_name, now)
            self._known.add(key)

        # 3) 분류 (체력은 바꾸지 않는다) + 잡담 연속 횟수 갱신
        #    사이에 await이 없어서 다른 메시지와 섞이지 않는다
        result = classify(message.content)
        streak = update_streak(
            self._streaks.get(team.id, Streak()), result.is_chitchat, message.created_at)
        self._streaks[team.id] = streak
        if not result.is_chitchat:                 # 진짜 대화·첨부 등: 횟수 초기화만 하고 끝
            return

        # 4) 정책이 행동을 고른다 -> 5) 분류 결과 기록 (같은 팀의 동시 처리를 막기 위해 락)
        nag = False
        stage = None
        count = streak.count
        async with repo.team_lock(team.id):
            mascot = await repo.get_mascot(db, team.id)
            stage = mascot.stage
            last_nag = await repo.get_last_nag(db, team.id)
            if decide(result, stage, last_nag, now, streak.count) is BotAction.NAG:
                await repo.set_last_nag(db, team.id, now)
                self._streaks[team.id] = Streak()          # 잔소리한 뒤에는 다시 센다
                nag = True
            await repo.add_classification(
                db, team_id=team.id, message_id=message.id, author_id=message.author.id,
                intents=result.intents, source=result.source, confidence=result.confidence,
                matched=result.matched, created_at=now,
            )

        if nag:
            line = f"{nag_line(stage)}\n-# ㅋㅋ·이모지만 {count}번 연속이야!"
            try:
                await message.reply(line, mention_author=False)
            except discord.HTTPException:
                try:
                    await message.channel.send(line)
                except discord.HTTPException:
                    log.warning("잔소리 전송 실패: channel=%s", message.channel.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ListenerCog(bot))