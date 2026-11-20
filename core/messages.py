# core/messages.py  (디스코드 import 금지)
from __future__ import annotations

import random

from core.state import Stage

STATUS_LINES: dict[Stage, tuple[str, ...]] = {
    Stage.NORMAL: (
        "오늘도 다들 열심히 하고 있네! 이 기세 좋아~",
        "팀이 잘 굴러가고 있어서 기분이 좋아요.",
    ),
    Stage.DENIAL: (
        "어? 다들 바쁜 거겠지? 괜찮아, 괜찮아...",
        "아직 별일 아니죠? 그냥 조용한 거죠?",
    ),
    Stage.ANGER: (
        "왜 아무도   얘기를 안 하는 거야!!",
        "지금 진행 상황 좀 알려줘!",
    ),
    Stage.BARGAINING: (
        "한 줄만이라도 공유해주면 안 될까...? 제발...",
        "딱 한 번만 진행 공유해주면 내가 잘할게...",
    ),
    Stage.DEPRESSION: (
        "...다들 나를 잊었나 봐.",
        "기운이 하나도 없어...",
    ),
    Stage.ACCEPTANCE: (
        "괜찮아. 이제 받아들일게... 그래도 누가 진행 하나만 공유해주면...",
        "...조용하네. 이게 끝일까.",
    ),
}


def status_line(stage: Stage, rng=random) -> str:
    return rng.choice(STATUS_LINES[stage])

# 단계에 "진입"했을 때 보내는 대사 (알림용)
ENTER_LINES: dict[Stage, str] = {
    Stage.NORMAL: "다시 기운이 나! 다들 고마워!",
    Stage.DENIAL: "어... 어? 요즘 진행 얘기가 없네? 아니야, 별일 아닐 거야.",
    Stage.ANGER: "화났어! 언제까지 이럴 거야? 진행 상황 좀 공유해줘!",
    Stage.BARGAINING: "저기... 오늘 한 일 한 줄만 적어주면 안 될까? 부탁이야...",
    Stage.DEPRESSION: "...다들 바쁜가 봐. 나는 여기 혼자 있을게.",
    Stage.ACCEPTANCE: "괜찮아, 받아들일게... 그래도 마음이 바뀌면 `/진행`으로 한 줄만 알려줘.",
}


def enter_line(stage: Stage) -> str:
    return ENTER_LINES[stage]


def acceleration_line(tier: float) -> str:
    if tier >= 2.0:
        return f"🔥 마감이 코앞이에요! 기운이 아주 빠르게 빠지고 있어요 (×{tier:g})"
    return f"⚡ 마감이 다가와요! 이제 기운이 더 빨리 빠져요 (×{tier:g})"

THANKS_LINES = (
    "고마워! 기운이 나는 것 같아.",
    "오, 진행 공유! 최고야.",
    "이렇게 알려주니까 든든해!",
)
REVIVE_LINE = "...눈이 떠졌어! 다들 고마워. 이제 정말 같이 해보자!"


def thanks_line(rng=random) -> str:
    return rng.choice(THANKS_LINES)

NAG_LINES: dict[Stage, tuple[str, ...]] = {
    Stage.ANGER: (
        "ㅋㅋ 할 시간에 진행 상황이나 공유해! 😡",
        "지금 웃음이 나와?!",
    ),
    Stage.BARGAINING: (
        "웃는 건 좋은데... 진행 한 줄만 올려주면 안 될까...?",
        "즐거워 보여서 좋긴 한데, 나 좀 봐줘... 열심히 하자...",
    ),
    Stage.DEPRESSION: (
        "...ㅋㅋ 소리만 들려. 나는 기운이 없어서 웃지도 못해.",
        "다들 즐거워 보이네... 나만 빼고.",
    ),
    Stage.ACCEPTANCE: (
        "...즐거워 보이네. 나를 살리려면 일 좀 하자.",
        "...괜찮아. 웃어도 돼. 그래도 마음이 있다면 `/진행`을.",
    ),
}


def nag_line(stage: Stage, rng=random) -> str:
    return rng.choice(NAG_LINES[stage])