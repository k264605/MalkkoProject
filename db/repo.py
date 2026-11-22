# db/repo.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

import aiosqlite

from config import RULES, team_now, utcnow
from core.state import Mascot, Team

UTC = timezone.utc


# ── 시각 변환 ────────────────────────────────────────
def to_db(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime은 저장할 수 없습니다 (tz-aware UTC를 쓰세요)")
    return dt.astimezone(UTC).isoformat(timespec="microseconds")   # 고정 형식


def _opt(dt: datetime | None) -> str | None:
    return to_db(dt) if dt is not None else None


def from_db(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


# ── 팀별 락: 같은 팀의 읽기-계산-쓰기를 한 번에 하나씩 ──
#   async with team_lock(team.id): (decay -> apply_action -> save_mascot)
_locks: dict[int, asyncio.Lock] = {}


def team_lock(team_id: int) -> asyncio.Lock:
    return _locks.setdefault(team_id, asyncio.Lock())


# ── 팀 ──────────────────────────────────────────────
@dataclass(frozen=True)
class TeamRow:
    id: int
    guild_id: int
    channel_id: int
    name: str
    start: datetime
    end: datetime
    demo_speed: float
    demo_offset_hours: float
    ai_enabled: bool
    created_at: datetime

    def to_core(self) -> Team:
        return Team(start=self.start, end=self.end)

    def now(self) -> datetime:
        """이 팀의 가상 현재 시각(배속·건너뛰기 반영). 게임 로직의 시각은 전부 이걸 쓴다."""
        return team_now(self.created_at, self.demo_speed, self.demo_offset_hours)


def _team(r: aiosqlite.Row) -> TeamRow:
    return TeamRow(
        id=r["id"], guild_id=r["guild_id"], channel_id=r["channel_id"], name=r["name"],
        start=datetime.fromisoformat(r["start_date"]),
        end=datetime.fromisoformat(r["end_date"]),
        demo_speed=r["demo_speed"], demo_offset_hours=r["demo_offset_hours"],
        ai_enabled=bool(r["ai_enabled"]),
        created_at=datetime.fromisoformat(r["created_at"]),
    )


async def _one(db: aiosqlite.Connection, sql: str, args: tuple = ()) -> aiosqlite.Row | None:
    async with db.execute(sql, args) as cur:
        return await cur.fetchone()


async def create_team(
    db: aiosqlite.Connection, *, guild_id: int, channel_id: int, name: str,
    start: datetime, end: datetime, created_at: datetime,
) -> TeamRow:
    """팀과 캐릭터(체력 100)를 함께 만든다. 같은 채널에 이미 있으면 sqlite3.IntegrityError."""
    try:
        cur = await db.execute(
            "INSERT INTO teams (guild_id, channel_id, name, start_date, end_date, "
            "orig_end_date, created_at) VALUES (?,?,?,?,?,?,?)",
            (guild_id, channel_id, name, to_db(start), to_db(end), to_db(end), to_db(created_at)),
        )
        team_id = cur.lastrowid
        await db.execute(
            "INSERT INTO mascots (team_id, hp, last_decay_at) VALUES (?,?,?)",
            (team_id, float(RULES.hp_max), to_db(created_at)),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    team = await get_team(db, team_id)
    assert team is not None
    return team


async def get_team(db: aiosqlite.Connection, team_id: int) -> TeamRow | None:
    r = await _one(db, "SELECT * FROM teams WHERE id=?", (team_id,))
    return _team(r) if r else None


async def get_team_by_channel(db: aiosqlite.Connection, channel_id: int) -> TeamRow | None:
    r = await _one(db, "SELECT * FROM teams WHERE channel_id=?", (channel_id,))
    return _team(r) if r else None


async def list_teams(db: aiosqlite.Connection) -> list[TeamRow]:
    async with db.execute("SELECT * FROM teams") as cur:
        return [_team(r) for r in await cur.fetchall()]


async def delete_team(db: aiosqlite.Connection, team_id: int) -> None:
    """팀과 딸린 데이터를 모두 삭제 (PRAGMA foreign_keys=ON 필요)."""
    await db.execute("DELETE FROM teams WHERE id=?", (team_id,))
    await db.commit()

async def update_team_demo(
    db: aiosqlite.Connection, team_id: int, *,
    start: datetime | None = None,
    end: datetime | None = None,
    demo_offset_hours: float | None = None,
    demo_speed: float | None = None,
) -> None:
    sets: list[str] = []
    args: list = []
    if start is not None:
        sets.append("start_date=?"); args.append(to_db(start))
    if end is not None:
        sets.append("end_date=?"); args.append(to_db(end))
    if demo_offset_hours is not None:
        sets.append("demo_offset_hours=?"); args.append(demo_offset_hours)
    if demo_speed is not None:
        sets.append("demo_speed=?"); args.append(demo_speed)
    if not sets:
        return
    await db.execute(f"UPDATE teams SET {', '.join(sets)} WHERE id=?", (*args, team_id))
    await db.commit()


async def reset_demo(db: aiosqlite.Connection, team_id: int) -> TeamRow:
    """/데모 초기화: 시계·기간 복원, 체력 100·정상, 행동 기록 삭제.
    데모 조작은 시작일과 마감일을 함께 옮겨 기간이 늘 같으므로, 시작일은 원래 마감일에서 거꾸로 구한다.
    오프셋이 0이 되면 가상 시각이 실제 시각으로 돌아가므로 last_decay_at도 지금으로 맞춘다.
    (행동 기록을 지우는 이유: 미래 시각의 기록이 남아 쿨다운이 꼬이는 걸 막기 위해)"""
    team = await get_team(db, team_id)
    if team is None:
        raise ValueError(f"team {team_id} not found")
    r = await _one(db, "SELECT orig_end_date FROM teams WHERE id=?", (team_id,))
    orig_end = datetime.fromisoformat(r["orig_end_date"])
    start = orig_end - (team.end - team.start)
    now = utcnow()
    try:
        await db.execute(
            "UPDATE teams SET demo_speed=1.0, demo_offset_hours=0.0, start_date=?, end_date=? "
            "WHERE id=?", (to_db(start), to_db(orig_end), team_id))
        await db.execute(
            "UPDATE mascots SET hp=?, skin_level=1, revive_count=0, acceptance_since=NULL, "
            "speed_tier=1.0, last_action_at=NULL, last_nag_at=NULL, last_decay_at=? "
            "WHERE team_id=?", (float(RULES.hp_max), to_db(now), team_id))
        await db.execute("DELETE FROM actions WHERE team_id=?", (team_id,))
        await db.execute("DELETE FROM stuck_requests WHERE team_id=?", (team_id,))
        await db.execute("DELETE FROM votes WHERE team_id=?", (team_id,))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    team = await get_team(db, team_id)
    assert team is not None
    return team


# ── 팀원 ────────────────────────────────────────────
async def ensure_member(
    db: aiosqlite.Connection, team_id: int, user_id: int, display_name: str, now: datetime,
) -> None:
    """처음 보는 사람이면 등록, 이미 있으면 표시 이름만 갱신."""
    await db.execute(
        "INSERT INTO members (team_id, user_id, display_name, joined_at) VALUES (?,?,?,?) "
        "ON CONFLICT(team_id, user_id) DO UPDATE SET display_name=excluded.display_name",
        (team_id, user_id, display_name, to_db(now)),
    )
    await db.commit()


async def count_members(db: aiosqlite.Connection, team_id: int) -> int:
    r = await _one(db, "SELECT COUNT(*) AS n FROM members WHERE team_id=?", (team_id,))
    return int(r["n"])


# ── 캐릭터 ──────────────────────────────────────────
async def get_mascot(db: aiosqlite.Connection, team_id: int) -> Mascot | None:
    r = await _one(db, "SELECT * FROM mascots WHERE team_id=?", (team_id,))
    if r is None:
        return None
    return Mascot(
        hp=r["hp"],
        last_decay_at=datetime.fromisoformat(r["last_decay_at"]),
        speed_tier=r["speed_tier"],
        acceptance_since=from_db(r["acceptance_since"]),
        last_action_at=from_db(r["last_action_at"]),
        revive_count=r["revive_count"],
        skin_level=r["skin_level"],
    )


async def save_mascot(db: aiosqlite.Connection, team_id: int, m: Mascot) -> None:
    await db.execute(
        "UPDATE mascots SET hp=?, skin_level=?, revive_count=?, acceptance_since=?, "
        "speed_tier=?, last_action_at=?, last_decay_at=? WHERE team_id=?",
        (m.hp, m.skin_level, m.revive_count, _opt(m.acceptance_since),
         m.speed_tier, _opt(m.last_action_at), to_db(m.last_decay_at), team_id),
    )
    await db.commit()


# ── 행동 기록 ───────────────────────────────────────
async def add_action(
    db: aiosqlite.Connection, team_id: int, user_id: int, kind, hp_delta: float,
    created_at: datetime, content: str = "",
) -> None:
    kind_value = kind.value if isinstance(kind, Enum) else str(kind)
    await db.execute(
        "INSERT INTO actions (team_id, user_id, kind, content, hp_delta, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (team_id, user_id, kind_value, content, hp_delta, to_db(created_at)),
    )
    await db.commit()


async def last_action_at(
    db: aiosqlite.Connection, team_id: int, user_id: int, kind,
) -> datetime | None:
    """이 사용자가 이 종류의 행동을 마지막으로 한 시각 (쿨다운 확인용)."""
    kind_value = kind.value if isinstance(kind, Enum) else str(kind)
    r = await _one(
        db, "SELECT MAX(created_at) AS t FROM actions WHERE team_id=? AND user_id=? AND kind=?",
        (team_id, user_id, kind_value))
    return from_db(r["t"]) if r else None


async def sharers_since(
    db: aiosqlite.Connection, team_id: int, since: datetime, kind="progress",
) -> frozenset[int]:
    """since 이후 해당 행동을 한 사람들 (부활 과반 계산용)."""
    kind_value = kind.value if isinstance(kind, Enum) else str(kind)
    async with db.execute(
        "SELECT DISTINCT user_id FROM actions WHERE team_id=? AND kind=? AND created_at>=?",
        (team_id, kind_value, to_db(since)),
    ) as cur:
        return frozenset(r["user_id"] for r in await cur.fetchall())

# ── 잔소리 시각 / 분류 기록 ─────────────────────────
async def get_last_nag(db: aiosqlite.Connection, team_id: int) -> datetime | None:
    r = await _one(db, "SELECT last_nag_at FROM mascots WHERE team_id=?", (team_id,))
    return from_db(r["last_nag_at"]) if r else None


async def set_last_nag(db: aiosqlite.Connection, team_id: int, at: datetime) -> None:
    await db.execute("UPDATE mascots SET last_nag_at=? WHERE team_id=?", (to_db(at), team_id))
    await db.commit()


async def add_classification(
    db: aiosqlite.Connection, *, team_id: int, message_id: int, author_id: int,
    intents, source: str, confidence: float, matched: str | None,
    created_at: datetime, offered: bool = False,
) -> None:
    """분류 결과만 기록한다. 메시지 내용은 저장하지 않는다."""
    intents_text = ",".join(i.value if isinstance(i, Enum) else str(i) for i in intents)
    await db.execute(
        "INSERT INTO classifications (team_id, message_id, author_id, intents, source, "
        "confidence, matched, offered, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (team_id, message_id, author_id, intents_text, source, confidence, matched,
         int(offered), to_db(created_at)),
    )
    await db.commit()

# ── 막힘 요청 ───────────────────────────────────────
@dataclass(frozen=True)
class StuckRow:
    id: int
    team_id: int
    requester_id: int
    content: str
    helper_id: int | None
    status: str                 # 'open' | 'helped'
    message_id: int | None
    created_at: datetime
    resolved_at: datetime | None


async def create_stuck_request(
    db: aiosqlite.Connection, team_id: int, requester_id: int, content: str, created_at: datetime,
) -> int:
    cur = await db.execute(
        "INSERT INTO stuck_requests (team_id, requester_id, content, created_at) VALUES (?,?,?,?)",
        (team_id, requester_id, content, to_db(created_at)),
    )
    await db.commit()
    return cur.lastrowid


async def set_stuck_message(db: aiosqlite.Connection, request_id: int, message_id: int) -> None:
    await db.execute("UPDATE stuck_requests SET message_id=? WHERE id=?", (message_id, request_id))
    await db.commit()


async def get_stuck_request(db: aiosqlite.Connection, request_id: int) -> StuckRow | None:
    r = await _one(db, "SELECT * FROM stuck_requests WHERE id=?", (request_id,))
    if r is None:
        return None
    return StuckRow(
        id=r["id"], team_id=r["team_id"], requester_id=r["requester_id"], content=r["content"],
        helper_id=r["helper_id"], status=r["status"], message_id=r["message_id"],
        created_at=datetime.fromisoformat(r["created_at"]), resolved_at=from_db(r["resolved_at"]),
    )


async def claim_stuck_request(
    db: aiosqlite.Connection, request_id: int, helper_id: int, now: datetime,
) -> bool:
    """열려 있는 요청을 이 사람이 맡는다. 이미 누가 맡았다면 False (한 요청에 한 명)."""
    cur = await db.execute(
        "UPDATE stuck_requests SET helper_id=?, status='helped', resolved_at=? "
        "WHERE id=? AND status='open'",
        (helper_id, to_db(now), request_id),
    )
    await db.commit()
    return cur.rowcount == 1

async def update_team_period(
    db: aiosqlite.Connection, team_id: int, start: datetime, end: datetime,
) -> None:
    """/설정: 기간 변경. 원래 마감일(orig_end_date)도 새 마감일로 맞춰서,
    /데모 초기화가 새 기간으로 돌아가게 한다."""
    await db.execute(
        "UPDATE teams SET start_date=?, end_date=?, orig_end_date=? WHERE id=?",
        (to_db(start), to_db(end), to_db(end), team_id),
    )
    await db.commit()

# ── 투표 ────────────────────────────────────────────
@dataclass(frozen=True)
class VoteRow:
    id: int
    team_id: int
    creator_id: int
    title: str
    options: tuple[str, ...]
    allow_multiple: bool
    message_id: int | None
    deadline: datetime
    closed: bool
    all_awarded: bool
    created_at: datetime


def _vote(r: aiosqlite.Row) -> VoteRow:
    return VoteRow(
        id=r["id"], team_id=r["team_id"], creator_id=r["creator_id"], title=r["title"],
        options=tuple(json.loads(r["options"])), allow_multiple=bool(r["allow_multiple"]),
        message_id=r["message_id"], deadline=datetime.fromisoformat(r["deadline"]),
        closed=bool(r["closed"]), all_awarded=bool(r["all_awarded"]),
        created_at=datetime.fromisoformat(r["created_at"]),
    )


async def create_vote(
    db: aiosqlite.Connection, *, team_id: int, creator_id: int, title: str, options,
    allow_multiple: bool, deadline: datetime, created_at: datetime,
) -> int:
    cur = await db.execute(
        "INSERT INTO votes (team_id, creator_id, title, options, allow_multiple, deadline, "
        "created_at) VALUES (?,?,?,?,?,?,?)",
        (team_id, creator_id, title, json.dumps(list(options), ensure_ascii=False),
         int(allow_multiple), to_db(deadline), to_db(created_at)),
    )
    await db.commit()
    return cur.lastrowid


async def set_vote_message(db: aiosqlite.Connection, vote_id: int, message_id: int) -> None:
    await db.execute("UPDATE votes SET message_id=? WHERE id=?", (message_id, vote_id))
    await db.commit()


async def get_vote(db: aiosqlite.Connection, vote_id: int) -> VoteRow | None:
    r = await _one(db, "SELECT * FROM votes WHERE id=?", (vote_id,))
    return _vote(r) if r else None


async def get_user_choices(db: aiosqlite.Connection, vote_id: int, user_id: int) -> set[int]:
    async with db.execute(
        "SELECT option_index FROM vote_responses WHERE vote_id=? AND user_id=?",
        (vote_id, user_id),
    ) as cur:
        return {r["option_index"] for r in await cur.fetchall()}


async def set_user_choices(
    db: aiosqlite.Connection, vote_id: int, user_id: int, choices: set[int],
) -> None:
    """이 사람의 선택을 통째로 교체한다 (빈 집합이면 투표 취소)."""
    try:
        await db.execute(
            "DELETE FROM vote_responses WHERE vote_id=? AND user_id=?", (vote_id, user_id))
        for idx in sorted(choices):
            await db.execute(
                "INSERT INTO vote_responses (vote_id, user_id, option_index) VALUES (?,?,?)",
                (vote_id, user_id, idx))
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def get_vote_responses(db: aiosqlite.Connection, vote_id: int) -> list[tuple[int, int]]:
    """[(user_id, option_index), ...]"""
    async with db.execute(
        "SELECT user_id, option_index FROM vote_responses WHERE vote_id=? "
        "ORDER BY option_index, user_id", (vote_id,),
    ) as cur:
        return [(r["user_id"], r["option_index"]) for r in await cur.fetchall()]


async def mark_all_awarded(db: aiosqlite.Connection, vote_id: int) -> None:
    await db.execute("UPDATE votes SET all_awarded=1 WHERE id=?", (vote_id,))
    await db.commit()


async def list_due_votes(db: aiosqlite.Connection, now: datetime) -> list[VoteRow]:
    async with db.execute(
        "SELECT * FROM votes WHERE closed=0 AND deadline<=?", (to_db(now),)
    ) as cur:
        return [_vote(r) for r in await cur.fetchall()]


async def close_vote(db: aiosqlite.Connection, vote_id: int, now: datetime) -> bool:
    """열려 있는 투표를 닫는다. 이미 닫혔다면 False (한 번만 마감 처리하려고)."""
    cur = await db.execute(
        "UPDATE votes SET closed=1, closed_at=? WHERE id=? AND closed=0", (to_db(now), vote_id))
    await db.commit()
    return cur.rowcount == 1


async def has_action(
    db: aiosqlite.Connection, team_id: int, user_id: int, kind, content: str,
) -> bool:
    kind_value = kind.value if isinstance(kind, Enum) else str(kind)
    r = await _one(
        db, "SELECT 1 AS x FROM actions WHERE team_id=? AND user_id=? AND kind=? AND content=? "
            "LIMIT 1", (team_id, user_id, kind_value, content))
    return r is not None