# ui/embeds.py
from __future__ import annotations
from db.repo import TeamRow, VoteRow
from datetime import datetime

import discord

from config import KST, RULES
from core.messages import status_line
from core.state import Mascot, Stage, hours_to_acceptance, speed_multiplier
from db.repo import TeamRow
from ui.translator import STAGE_KO
from ui.images import attach, stage_image

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
    use_emoji: bool = True,
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

def card_kwargs(
    team: TeamRow,
    m: Mascot,
    now: datetime,
    revive: tuple[int, int] | None = None,
    headline: str | None = None,
) -> dict:
    """상태 카드 + 캐릭터 이미지. send / send_message / followup.send에 `**`로 넘긴다.
    단계 이미지가 있으면 큰 이미지로 붙이고, 없으면 이모지 카드만 나간다."""
    path = stage_image(m.stage, m.skin_level)
    embed = build_status_card(team, m, now, revive, headline, use_emoji=path is None)
    return {"embed": embed, **attach(embed, path, as_name=m.stage.value)}

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

def build_stuck_card(requester_id: int, content: str, helper_id: int | None = None) -> discord.Embed:
    """막힘 요청 카드. helper_id가 있으면 '도움 받는 중' 상태로 바꾼다."""
    if helper_id is None:
        embed = discord.Embed(title="🆘 막힌 곳이 있어요", description=content, color=0xFAA61A)
        embed.add_field(name="요청자", value=f"<@{requester_id}>", inline=True)
        embed.add_field(name="상태", value="🕐 도와줄 팀원을 기다리는 중", inline=True)
        embed.set_footer(text="도와주면 말꼬가 체력 +20 회복해요 · 요청자는 도울 수 없어요")
    else:
        embed = discord.Embed(title="✅ 막힘 해결 중", description=content, color=0x57F287)
        embed.add_field(name="요청자", value=f"<@{requester_id}>", inline=True)
        embed.add_field(name="도와주는 사람", value=f"🙌 <@{helper_id}>", inline=True)
    return embed

def _day(dt: datetime) -> str:
    return f"{dt.astimezone(KST):%Y-%m-%d}"


def _change(old: str, new: str) -> str:
    return new if old == new else f"{old} → **{new}**"


def build_settings_card(
    team: TeamRow, now: datetime, old: TeamRow | None = None, old_now: datetime | None = None,
) -> discord.Embed:
    """기간 설정 카드. old를 주면 '변경 전 → 변경 후'로 보여준다."""
    start, end = _day(team.start), _day(team.end)
    dday, speed = dday_text(team.end, now), speed_text(team, now)
    days = f"{(team.end - team.start).total_seconds() / 86400:.0f}일"
    t_hours = f"{hours_to_acceptance(team.start, team.end):.0f}시간"

    if old is not None and old_now is not None:
        start = _change(_day(old.start), start)
        end = _change(_day(old.end), end)
        dday = _change(dday_text(old.end, old_now), dday)
        speed = _change(speed_text(old, old_now), speed)
        days = _change(f"{(old.end - old.start).total_seconds() / 86400:.0f}일", days)
        t_hours = _change(f"{hours_to_acceptance(old.start, old.end):.0f}시간", t_hours)

    changed = old is not None
    embed = discord.Embed(
        title="⚙️ 기간을 변경했어요" if changed else "⚙️ 현재 설정", color=0x5865F2)
    embed.add_field(name="시작일", value=start, inline=True)
    embed.add_field(name="마감일", value=end, inline=True)
    embed.add_field(name="마감까지", value=dday, inline=True)
    embed.add_field(name="프로젝트 기간", value=days, inline=True)
    embed.add_field(name="풀 체력에서 수용까지", value=t_hours, inline=True)
    embed.add_field(name="악화 속도", value=speed, inline=False)
    embed.set_footer(
        text="체력은 바뀌지 않아요 · 변경 전까지의 감소는 이미 반영했어요" if changed
        else "`/설정 시작일: … 마감일: …`으로 바꿀 수 있어요")
    return embed

def build_vote_card(
    vote: VoteRow, counts: list[int], by_option: dict[int, list[int]],
    voter_count: int, member_count: int, closed: bool = False,
) -> discord.Embed:
    ts = int(vote.deadline.timestamp())
    mode = "여러 개 선택 가능" if vote.allow_multiple else "한 개만 선택 (다시 누르면 취소)"
    state = "🏁 마감됐어요" if closed else f"⏰ 마감 <t:{ts}:F> (<t:{ts}:R>)"
    embed = discord.Embed(
        title=f"🗳️ {vote.title}", description=f"{state}\n🔘 {mode}",
        color=0x99AAB5 if closed else 0x5865F2)

    top = max(counts, default=0)
    for i, label in enumerate(vote.options):
        n = counts[i]
        filled = round(n / voter_count * 10) if voter_count else 0
        bar = "▰" * filled + "▱" * (10 - filled)
        crown = "👑 " if closed and top > 0 and n == top else ""
        who = " ".join(f"<@{u}>" for u in by_option.get(i, [])[:10])
        value = f"`{bar}` **{n}명**" + (f"\n{who}" if who else "")
        embed.add_field(name=f"{crown}{i + 1}. {label}", value=value, inline=False)

    footer = f"참여 {voter_count}/{member_count}명"
    if not closed:
        footer += " · 처음 투표하면 말꼬 체력 +10, 전원이 참여하면 +20"
    embed.set_footer(text=footer)
    return embed