# ui/images.py
from __future__ import annotations

import logging
from pathlib import Path

import discord

from config import settings
from core.state import Stage

log = logging.getLogger("malkko.images")

EXTS = (".gif", ".png", ".webp")
MOTIONS = ("happy", "healthy", "shine")
MAX_BYTES = 2 * 1024 * 1024        # 설계서: GIF 1개 2MB 이하

# 이미지가 없을 때의 대체 표시
STAGE_EMOJI = {
    Stage.NORMAL: "😊", Stage.DENIAL: "😐", Stage.ANGER: "😡",
    Stage.BARGAINING: "🥺", Stage.DEPRESSION: "😞", Stage.ACCEPTANCE: "😶‍🌫️",
}
STAGE_COLOR = {
    Stage.NORMAL: 0x57F287, Stage.DENIAL: 0xFEE75C, Stage.ANGER: 0xED4245,
    Stage.BARGAINING: 0xEB459E, Stage.DEPRESSION: 0x5865F2, Stage.ACCEPTANCE: 0x99AAB5,
}
# 한국어 표시는 ui/translator.py로 옮겨도 된다
STAGE_KO = {
    Stage.NORMAL: "정상", Stage.DENIAL: "부정", Stage.ANGER: "분노",
    Stage.BARGAINING: "협상", Stage.DEPRESSION: "우울", Stage.ACCEPTANCE: "수용",
}


def _find(name: str, skin_level: int = 1) -> Path | None:
    key = settings.character_key
    stems = []
    if skin_level > 1:
        stems.append(f"{key}_{name}_lv{skin_level}")
    stems.append(f"{key}_{name}")
    for stem in stems:
        for ext in EXTS:
            path = settings.assets_dir / f"{stem}{ext}"
            if path.exists():
                return path
    return None


def stage_image(stage: Stage, skin_level: int = 1) -> Path | None:
    return _find(stage.value, skin_level)


def motion_image(motion: str, skin_level: int = 1) -> Path | None:
    return _find(motion, skin_level)


def attach(embed: discord.Embed, path: Path | None, as_name: str) -> dict:
    """임베드에 이미지를 붙이고, send_message/send에 `**`로 넘길 kwargs를 돌려준다.
    파일이 없으면 빈 dict라서 임베드만 나간다.
    파일명은 한글이 섞여도 안 깨지게 영문 as_name으로 바꿔 올린다."""
    if path is None:
        return {}
    filename = f"{as_name}{path.suffix}"
    embed.set_image(url=f"attachment://{filename}")
    return {"file": discord.File(path, filename=filename)}


def check_assets() -> None:
    """시작할 때 한 번 호출: 없는 파일과 용량 초과를 로그로 알려준다."""
    if not settings.assets_dir.exists():
        log.warning("assets 폴더가 없습니다: %s", settings.assets_dir)
        return
    for stage in Stage:
        if stage_image(stage) is None:
            log.warning("단계 이미지 없음: %s_%s.(gif|png|webp)", settings.character_key, stage.value)
    for motion in MOTIONS:
        if motion_image(motion) is None:
            log.warning("모션 이미지 없음: %s_%s.(gif|png|webp)", settings.character_key, motion)
    for path in settings.assets_dir.iterdir():
        if path.suffix.lower() in EXTS and path.stat().st_size > MAX_BYTES:
            log.warning("%s: %.1fMB (2MB 초과)", path.name, path.stat().st_size / 1024 / 1024)