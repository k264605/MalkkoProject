# core/voting.py  (디스코드 import 금지)
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from config import KST

_RELATIVE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(분|min|m|시간|hr|h|일|d)\s*$", re.IGNORECASE)
FORMAT_HELP = "예: 30분, 2시간, 1일, 18:00, 11-25 18:00, 2026-11-25 18:00"


def _hour_minute(text: str) -> tuple[int, int]:
    h, m = text.split(":")
    return int(h), int(m)


def parse_deadline(text: str, now: datetime) -> datetime:
    """마감 시각 문자열 -> UTC datetime.
    '30분' '2시간' '1일' '30m' '2h' '1d'는 now 기준 상대 시간,
    '18:00'은 다음에 오는 그 시각, '11-25 18:00' / '2026-11-25 18:00'은 한국 시간 기준이다."""
    t = text.strip()
    rel = _RELATIVE.match(t)
    if rel:
        value, unit = float(rel.group(1)), rel.group(2).lower()
        if unit in ("분", "min", "m"):
            return now + timedelta(minutes=value)
        if unit in ("시간", "hr", "h"):
            return now + timedelta(hours=value)
        return now + timedelta(days=value)

    local_now = now.astimezone(KST)
    parts = t.replace("/", "-").replace(".", "-").split()
    try:
        if len(parts) == 1 and ":" in parts[0]:
            hh, mm = _hour_minute(parts[0])
            dt = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt <= local_now:
                dt += timedelta(days=1)
        elif len(parts) == 2:
            nums = [int(x) for x in parts[0].split("-")]
            if len(nums) == 2:
                nums = [local_now.year, *nums]
            if len(nums) != 3:
                raise ValueError
            hh, mm = _hour_minute(parts[1])
            dt = datetime(*nums, hh, mm, tzinfo=KST)
        else:
            raise ValueError
    except ValueError:
        raise ValueError(f"마감 형식이 올바르지 않아요. {FORMAT_HELP}") from None
    return dt.astimezone(timezone.utc)


def toggle_choice(current: set[int], index: int, allow_multiple: bool) -> set[int]:
    """버튼을 눌렀을 때의 새 선택.
    중복 가능: 그 항목을 켜고 끈다. 단일 선택: 그 항목으로 바꾸고, 이미 그 항목이면 취소."""
    if allow_multiple:
        return set(current) ^ {index}
    return set() if set(current) == {index} else {index}


def tally(option_count: int, responses) -> list[int]:
    """responses: [(user_id, option_index), ...] -> 항목별 득표 수"""
    counts = [0] * option_count
    for _user, idx in responses:
        if 0 <= idx < option_count:
            counts[idx] += 1
    return counts


def voter_set(responses) -> set[int]:
    return {user for user, _ in responses}


def voters_by_option(responses) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for user, idx in responses:
        result.setdefault(idx, []).append(user)
    return result


def winners(counts: list[int]) -> list[int]:
    """최다 득표 항목의 번호들 (동률이면 여러 개, 아무도 투표 안 했으면 빈 목록)."""
    top = max(counts, default=0)
    return [] if top == 0 else [i for i, c in enumerate(counts) if c == top]


def is_everyone(voters: int, member_count: int) -> bool:
    """등록된 팀원 전원이 투표했는가."""
    return member_count >= 1 and voters >= member_count