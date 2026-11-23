# config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

KST = timezone(timedelta(hours=9), "KST")


# ── 1. 환경 설정 ─────────────────────────────────────
@dataclass(frozen=True)
class Settings:
    token: str
    db_path: Path
    dev_guild_id: int | None   # 개발 중 슬래시 커맨드를 이 서버에만 즉시 동기화
    assets_dir: Path
    character_key: str
    sync_scope: str


def _load_settings() -> Settings:
    # 토큰이 없어도 여기서는 멈추지 않는다 (core 테스트가 .env 없이 돌 수 있게).
    # 봇을 실제로 실행할 때 bot.py에서 확인한다.
    token = os.getenv("DISCORD_TOKEN", "")
    dev_guild = os.getenv("DEV_GUILD_ID")

    # DEV_GUILD_ID가 있으면 기본은 개발용(guild), 없으면 모든 서버용(global)
    scope = os.getenv("SYNC_SCOPE", "guild" if dev_guild else "global").lower()
    if scope not in ("guild", "global"):
        raise RuntimeError("SYNC_SCOPE는 guild 또는 global이어야 합니다.")
    if scope == "guild" and not dev_guild:
        raise RuntimeError("SYNC_SCOPE=guild 에는 DEV_GUILD_ID가 필요합니다.")

    return Settings(
        token=token,
        db_path=BASE_DIR / os.getenv("DB_PATH", "malkko.db"),
        dev_guild_id=int(dev_guild) if dev_guild else None,
        assets_dir=BASE_DIR / "assets",
        character_key=os.getenv("CHARACTER_KEY", "malkko"),
        sync_scope=scope,
    )



settings = _load_settings()


# ── 2. 규칙 초기값 ───────────────────────────────────
@dataclass(frozen=True)
class Rules:
    hp_max: int = 100
    hp_decay_span: int = 84          # 100 -> 16(수용 진입)까지의 체력폭
    acceptance_ratio: float = 0.10   # T = 전체 기간의 10%
    acceptance_min_hours: float = 48
    acceptance_max_hours: float = 168
    # (남은 기간 비율 이하, 배수) — 작은 비율부터 검사
    speed_tiers: tuple[tuple[float, float], ...] = ((0.10, 2.0), (0.25, 1.5))
    # 단계 하한 체력. 위에서부터 나빠지는 순서이고, 이름은 core/state.py의 Stage 값과 같아야 한다
    # (core/state.py의 STAGE_FLOORS가 이 값을 읽어서 만든다)
    stage_floors: tuple[tuple[str, int], ...] = (
        ("normal", 84), ("denial", 67), ("anger", 50),
        ("bargaining", 34), ("depression", 17), ("acceptance", 0),
    )


RULES = Rules()


# ── 3. 시계 ──────────────────────────────────────────
def utcnow() -> datetime:
    """실제 현재 시각 (UTC, tz-aware)."""
    return datetime.now(timezone.utc)


def team_now(
    anchor: datetime,
    demo_speed: float = 1.0,
    demo_offset_hours: float = 0.0,
) -> datetime:
    """팀의 가상 현재 시각.

    anchor 이후 흐른 실제 시간에 배속을 곱하고, 오프셋을 더한다.
    배속 1.0 / 오프셋 0이면 실제 시각과 같다.
    """
    real_elapsed = utcnow() - anchor
    return anchor + real_elapsed * demo_speed + timedelta(hours=demo_offset_hours)

def kst_start_of_day(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=KST).astimezone(timezone.utc)


def kst_end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=KST).astimezone(timezone.utc)