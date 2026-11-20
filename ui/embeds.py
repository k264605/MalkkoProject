# ui/embeds.py
from __future__ import annotations

from datetime import datetime

import discord

from config import KST, RULES
from core.messages import status_line
from core.state import Mascot, Stage, hours_to_acceptance, speed_multiplier
from db.repo import TeamRow
from ui.translator import STAGE_KO

from core.state import Change, Mascot, Stage, hours_to_acceptance, speed_multiplier

STAGE_EMOJI = {
    Stage.NORMAL: "😊", Stage.DENIAL: "😐", Stage.ANGER: "😡",
    Stage.BARGAINING: "🥺", Stage.DEPRESSION: "😞", Stage.ACCEPTANCE: "😶",
}
STAGE_COLOR = {
    Stage.NORMAL: 0x57F287, Stage.DENIAL: 0xFEE75C, Stage.ANGER: 0xED4245,
    Stage.BARGAINING: 0xEB459E, Stage.DEPRESSION: 0x5865F2, Stage.ACCEPTANCE: 0x99AAB5,
}
MOTION_EMOJI = {"happy": "😆", "healthy": "💪", "shine": "✨"}


def hp_bar(hp: float, width: int = 10) -> str:
    filled = int(hp / RULES.hp_max * width)
    return "█" * filled + "░" * (width - filled)


def dday_text(end: datetime, now: datetime) -> str:
    if now >= end:
        return "마감 지남"
    d = (end.astimezone(KST).date() - now.astimezone(KST).date()).days
    return "D-Day" if d == 0 else f"D-{d}"


def speed_text(team: TeamRow, now: datetime) -> str:
    if now < team.start:
        return "시작 전"
    mult = speed_multiplier(team.start, team.end, now)
    if mult == 0:
        return "정지 (마감 후)"
    per_hour = RULES.hp_decay_span / hours_to_acceptance(team.start, team.end) * mult
    label = "보통" if mult == 1 else f"가속 ×{mult:g}"
    return f"{label} · 시간당 -{per_hour:.2f}"


def build_status_card(
    team: TeamRow,
    m: Mascot,
    now: datetime,
    revive: tuple[int, int] | None = None,   # (공유한 인원, 필요 인원)
    headline: str | None = None,
) -> discord.Embed:
    """상태 카드. 캐릭터 이미지는 나중에 이 함수 한 곳에서 붙인다."""
    stage = m.stage
    embed = discord.Embed(
        title=f"{STAGE_EMOJI[stage]} {team.name} · {STAGE_KO[stage]}",
        description=f"*“{headline or status_line(stage)}”*",
        color=STAGE_COLOR[stage],
    )
    embed.add_field(name="체력", value=f"`{hp_bar(m.hp)}` {int(m.hp)}/{RULES.hp_max}", inline=False)
    embed.add_field(name="마감", value=dday_text(team.end, now), inline=True)
    embed.add_field(name="악화 속도", value=speed_text(team, now), inline=True)
    if m.revive_count:
        embed.add_field(name="부활 횟수", value=f"{m.revive_count}회", inline=True)
    if revive is not None:
        done, need = revive
        embed.add_field(
            name="부활 미션",
            value=f"`/진행`으로 진행 상황을 공유해 주세요! ({done}/{need}명)",
            inline=False,
        )

    footer = f"마감 {team.end.astimezone(KST):%Y-%m-%d} (KST)"
    if team.demo_offset_hours or team.demo_speed != 1.0:
        footer += f" · 🧪 데모 모드 (가상 시각 {now.astimezone(KST):%m-%d %H:%M})"
    embed.set_footer(text=footer)
    return embed

def describe_change(change: Change | None) -> str:
    """'체력 100 → 70 · 정상 → 부정 · ⚡ 가속 ×2' 같은 한 줄 요약. 변화가 없으면 빈 문자열."""
    if change is None:
        return ""
    b, a = change.before, change.after
    parts = []
    if int(b.hp) != int(a.hp):
        parts.append(f"체력 {int(b.hp)} → {int(a.hp)}")
    if change.stage_changed:
        parts.append(f"{STAGE_KO[b.stage]} → {STAGE_KO[a.stage]}")
    if change.entered_acceleration:
        parts.append(f"⚡ 가속 ×{a.speed_tier:g}")
    return " · ".join(parts)