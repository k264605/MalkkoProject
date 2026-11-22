from datetime import datetime, timedelta, timezone

import pytest

from core.classify import classify
from core.policy import BotAction, decide
from core.state import Stage
from core.policy import NAG_STREAK, STREAK_WINDOW, Streak, update_streak

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("text", [
    "ㅋㅋ", "ㅋㅋㅋㅋㅋㅋ", "ㅎㅎ", "ㅠㅠ", "ㅜㅜ", "ㅋ ㅋ ㅋ", "ㅋㅋ!!", "!!!", "...", "?",
    "~~~", "^^", "😂", "😂😂😂", "ㅋㅋ 😂", "❤️", "👍🏽",
    "<:pepe:123456789>", "<a:dance:987654321>",
])
def test_chitchat(text):
    assert classify(text).is_chitchat


@pytest.mark.parametrize("text", [
    "", "   ", "ㅋㅋ 진행 어때", "ok", "lol", "123", "진행했어요", "ㅇㅇ", "ㅡㅡ",
    "ㅋㅋ https://example.com",
])
def test_not_chitchat(text):
    assert not classify(text).is_chitchat


def test_classification_never_contains_message_text():
    r = classify("ㅋㅋ")
    assert r.source == "A" and r.matched == "chitchat_only"


CHAT = classify("ㅋㅋ")
WORK = classify("진행했어요")


@pytest.mark.parametrize("stage", [Stage.NORMAL, Stage.DENIAL])
def test_no_nag_before_anger(stage):
    assert decide(CHAT, stage, None, NOW) is BotAction.NONE


@pytest.mark.parametrize("stage", [Stage.ANGER, Stage.BARGAINING, Stage.DEPRESSION, Stage.ACCEPTANCE])
def test_nag_from_anger(stage):
    assert decide(CHAT, stage, None, NOW) is BotAction.NAG


def test_nag_cooldown_one_hour():
    assert decide(CHAT, Stage.ANGER, NOW - timedelta(minutes=30), NOW) is BotAction.NONE
    assert decide(CHAT, Stage.ANGER, NOW - timedelta(hours=1), NOW) is BotAction.NAG


def test_non_chitchat_never_nags():
    assert decide(WORK, Stage.ACCEPTANCE, None, NOW) is BotAction.NONE

def test_streak_counts_consecutive_chitchat():
    s = Streak()
    for i in range(3):
        s = update_streak(s, True, NOW + timedelta(minutes=i))
    assert s.count == 3


def test_streak_resets_on_real_message():
    s = update_streak(update_streak(Streak(), True, NOW), True, NOW)
    assert update_streak(s, False, NOW) == Streak()


def test_streak_restarts_after_window():
    s = update_streak(Streak(), True, NOW)
    s = update_streak(s, True, NOW + STREAK_WINDOW + timedelta(seconds=1))
    assert s.count == 1


def test_no_nag_until_streak_reached():
    assert decide(CHAT, Stage.ANGER, None, NOW, chitchat_streak=NAG_STREAK - 1) is BotAction.NONE
    assert decide(CHAT, Stage.ANGER, None, NOW, chitchat_streak=NAG_STREAK) is BotAction.NAG