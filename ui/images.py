# ui/images.py
from __future__ import annotations

import logging
from pathlib import Path

import discord

from config import settings
from core.state import Stage

log = logging.getLogger("malkko.images")

EXTS = (".png", ".gif", ".webp")        # 먼저 찾는 순서
MAX_BYTES = 2 * 1024 * 1024             # 설계서: 이미지 1개 2MB 이하
IMAGE_STYLE = "image"                   # "image": 카드 안의 큰 이미지 / "thumbnail": 작은 썸네일


def _find(name: str, skin_level: int = 1) -> Path | None:
    """{키}_{이름}_lv{N} -> ... -> {키}_{이름} 순서로 찾는다 (외형 레벨 파일이 없으면 기본으로 대체)."""
    key = settings.character_key
    stems = [f"{key}_{name}_lv{lv}" for lv in range(skin_level, 1, -1)]
    stems.append(f"{key}_{name}")
    for stem in stems:
        for ext in EXTS:
            path = settings.assets_dir / f"{stem}{ext}"
            if path.exists():
                return path
    return None


def stage_image(stage: Stage, skin_level: int = 1) -> Path | None:
    return _find(stage.value, skin_level)


def attach(embed: discord.Embed, path: Path | None, as_name: str) -> dict:
    """임베드에 이미지를 붙이고, send에 `**`로 넘길 kwargs를 돌려준다. 파일이 없으면 빈 dict.
    한글 파일명이 깨지지 않도록 영문 as_name으로 바꿔서 올린다."""
    if path is None:
        return {}
    filename = f"{as_name}{path.suffix.lower()}"
    url = f"attachment://{filename}"
    if IMAGE_STYLE == "thumbnail":
        embed.set_thumbnail(url=url)
    else:
        embed.set_image(url=url)
    return {"file": discord.File(path, filename=filename)}


def check_assets() -> None:
    """시작할 때 한 번: 연결된 이미지 수, 빠진 단계, 용량 초과를 로그로 알려준다."""
    if not settings.assets_dir.exists():
        log.warning("assets 폴더가 없습니다: %s", settings.assets_dir)
        return
    found = 0
    for stage in Stage:
        path = stage_image(stage)
        if path is None:
            log.warning("단계 이미지 없음 (이모지로 대체): %s_%s.(png|gif|webp)",
                        settings.character_key, stage.value)
            continue
        found += 1
        if path.stat().st_size > MAX_BYTES:
            log.warning("%s: %.1fMB (2MB 초과)", path.name, path.stat().st_size / 1024 / 1024)
    log.info("캐릭터 이미지 %d/%d개 연결됨", found, len(Stage))