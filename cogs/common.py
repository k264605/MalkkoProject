# cogs/common.py  (cog가 아니라 공용 함수 모음)
from __future__ import annotations

import logging
from datetime import datetime

import aiosqlite
import discord
from discord.ext import commands

from core.actions import revive_required
from core.messages import acceleration_line, enter_line
from core.state import Change, Mascot, Stage, decay
from db import repo
from db.repo import TeamRow
from ui.embeds import build_status_card
from ui.translator import STAGE_KO

import contextlib

log = logging.getLogger("malkko.common")


async def settle(
    db: aiosqlite.Connection, team: TeamRow, now: datetime, *, save: bool, lock: bool = True,
) -> tuple[Mascot, Change | None]:
    """캐릭터를 불러와 now까지의 감소를 반영한다.
    save=False면 계산만 하고(/상태 같은 읽기용), True면 저장한다(스케줄러·명령어용).
    lock=False는 호출하는 쪽이 이미 repo.team_lock을 잡고 있을 때만 쓴다 (락은 재진입 불가)."""
    if not save:
        m = await repo.get_mascot(db, team.id)
        change = decay(m, team.to_core(), now)
        return (change.after if change else m), change

    guard = repo.team_lock(team.id) if lock else contextlib.nullcontext()
    async with guard:
        m = await repo.get_mascot(db, team.id)
        change = decay(m, team.to_core(), now)
        if change is None:
            return m, None
        await repo.save_mascot(db, team.id, change.after)
        return change.after, change


async def revive_info(db: aiosqlite.Connection, team: TeamRow, m: Mascot) -> tuple[int, int] | None:
    """수용 단계일 때만 (진행 공유한 인원, 필요 인원)."""
    if m.stage is not Stage.ACCEPTANCE or m.acceptance_since is None:
        return None
    sharers = await repo.sharers_since(db, team.id, m.acceptance_since)
    need = revive_required(await repo.count_members(db, team.id))
    return len(sharers), need


def needs_announce(change: Change | None) -> bool:
    """알림 조건: 단계가 바뀌었거나 가속 구간에 막 들어갔을 때만."""
    return change is not None and (change.stage_changed or change.entered_acceleration)


async def announce(bot: commands.Bot, team: TeamRow, change: Change, now: datetime) -> None:
    """팀 채널에 단계 변경·가속 알림을 보낸다 (대사 + 상태 카드)."""
    channel = bot.get_channel(team.channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(team.channel_id)
        except discord.HTTPException:
            log.warning("알림 채널을 찾을 수 없음: team=%s channel=%s", team.id, team.channel_id)
            return
    if not hasattr(channel, "send"):
        return

    b, a = change.before, change.after
    lines: list[str] = []
    if change.stage_changed:
        arrow = "📉" if change.stage_dropped else "📈"
        lines.append(f"{arrow} **{STAGE_KO[b.stage]} → {STAGE_KO[a.stage]}**")
    if change.entered_acceleration:
        lines.append(acceleration_line(a.speed_tier))

    revive = await revive_info(bot.db, team, a)
    headline = enter_line(a.stage) if change.stage_changed else None
    embed = build_status_card(team, a, now, revive, headline=headline)
    try:
        await channel.send(content="\n".join(lines), embed=embed)
    except discord.HTTPException:
        log.exception("알림 전송 실패: team=%s", team.id)