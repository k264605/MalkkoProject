# core/classify.py  (디스코드 import 금지)
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    CHITCHAT = "chitchat"      # A: 명백한 잡담
    # PROGRESS / STUCK / MEETING은 B 단계에서 추가


@dataclass(frozen=True)
class Classification:
    intents: tuple[Intent, ...] = ()
    source: str = "A"
    confidence: float = 0.0
    matched: str | None = None      # 규칙 이름. 메시지 내용은 넣지 않는다.

    @property
    def is_chitchat(self) -> bool:
        return Intent.CHITCHAT in self.intents


CHITCHAT_JAMO = frozenset("ㅋㅎㅠㅜ")
_CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")      # 디스코드 커스텀 이모지 <:이름:ID>


def _is_chitchat_char(ch: str) -> bool:
    if ch.isspace() or ch in CHITCHAT_JAMO:
        return True
    cat = unicodedata.category(ch)
    # P: 문장부호, S: 기호(이모지 포함), Mn/Me/Cf: 이모지 결합 문자(변형 선택자, ZWJ 등)
    return cat[0] in ("P", "S") or cat in ("Mn", "Me", "Cf")


def classify(text: str) -> Classification:
    """A 분류: ㅋ ㅎ ㅠ ㅜ, 문장부호, 이모지로만 이루어진 메시지만 잡담으로 본다.
    글자가 하나라도 섞여 있으면 판단하지 않는다(빈 결과)."""
    if not text.strip():
        return Classification()
    rest = _CUSTOM_EMOJI.sub("", text)
    if all(_is_chitchat_char(ch) for ch in rest):
        return Classification(
            intents=(Intent.CHITCHAT,), source="A", confidence=1.0, matched="chitchat_only")
    return Classification()