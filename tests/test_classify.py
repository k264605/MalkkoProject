from datetime import datetime, timedelta, timezone

import pytest

from core.classify import classify
from core.policy import BotAction, decide
from core.state import Stage

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