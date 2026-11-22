# ui/translator.py
from __future__ import annotations

import discord
from discord import app_commands

from core.state import Stage

STAGE_KO: dict[Stage, str] = {
    Stage.NORMAL: "정상", Stage.DENIAL: "부정", Stage.ANGER: "분노",
    Stage.BARGAINING: "협상", Stage.DEPRESSION: "우울", Stage.ACCEPTANCE: "수용",
}

# 코드의 영어 이름 -> 한국어 이름 (소문자, 공백 없이)
KO_NAMES: dict[str, str] = {
    "mascotstart": "말꼬-시작",
    "status": "상태",
    "progress": "진행",
    "stuck": "막힘",
    "meetingvote": "회의-투표",
    "settings": "설정",
    "demo": "데모",
    # 옵션 이름
    "name": "이름",
    "start_date": "시작일",
    "end_date": "마감일",
    "skip": "건너뛰기",
    "deadline": "마감",
    "reset": "초기화",
    "hours": "시간",
    "days": "남은일수",
    "content": "내용",
    "meeting-vote": "회의-투표",
    "title": "제목",
    "option1": "후보1",
    "option2": "후보2",
    "option3": "후보3",
    "option4": "후보4",
    "option5": "후보5",
    "multiple": "중복선택",

}


class KoTranslator(app_commands.Translator):
    async def translate(
        self,
        string: app_commands.locale_str,
        locale: discord.Locale,
        context: app_commands.TranslationContext,
    ) -> str | None:
        if locale is not discord.Locale.korean:
            return None
        return KO_NAMES.get(string.message)